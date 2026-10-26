"""Single-worker polling of the configured Threads account; never publishes posts."""
import asyncio
import hashlib
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import requests
from fastapi import APIRouter, HTTPException
from google.api_core.exceptions import GoogleAPICallError
from pydantic import BaseModel, ConfigDict

from app.database import get_database
from app.analysis_records import observation
from app.followers import collect_followers
from app.reply_views import sync_reply_views
from app.account_views import collect_account_views
from app.profile_snapshot import ProfileSnapshot, save_snapshot

BASE_URL = 'https://graph.threads.net/v1.0'
METRICS = ('views', 'likes', 'replies', 'reposts', 'quotes')
router = APIRouter(prefix='/api/v1/sync', tags=['sync'])
lock = threading.Lock()
next_insight_check = {}
manual_lock = threading.Lock()
manual_state = {'status': 'idle', 'started_at': None, 'finished_at': None,
                'result': None, 'errors': []}
state = {'running': False, 'last_success_at': None, 'last_error': None,
         'last_result': None, 'followers_error': None, 'replies_error': None,
         'account_views_error': None, 'account_views_last_success_at': None, 'progress': None}


class SyncError(Exception):
    pass


def api_get(session, path, params):
    try:
        response = session.get(f'{BASE_URL}/{path}', params=params, timeout=20)
        payload = response.json()
    except (requests.RequestException, ValueError):
        raise SyncError('threads_network_error') from None
    if response.status_code != 200 or 'error' in payload:
        code = payload.get('error', {}).get('code')
        if code == 190:
            raise SyncError('threads_token_expired_or_invalid')
        if response.status_code == 429 or code in (4, 32, 613):
            raise SyncError('threads_rate_limited')
        raise SyncError('threads_api_error')
    if not isinstance(payload.get('data'), list):
        raise SyncError('threads_invalid_response')
    return payload


def fetch_posts(session):
    posts, after, seen = [], None, set()
    for _ in range(100):
        params = {'fields': 'id,text,timestamp,media_type,permalink', 'limit': 100}
        if after:
            params['after'] = after
        payload = api_get(session, 'me/threads', params)
        posts.extend(payload['data'])
        paging = payload.get('paging', {})
        if not paging.get('next'):
            return posts
        after = paging.get('cursors', {}).get('after')
        if not after or after in seen:
            raise SyncError('threads_invalid_pagination')
        seen.add(after)
    raise SyncError('threads_page_limit_exceeded')


def sync_once(force=False):
    if not lock.acquire(blocking=False):
        return {'status': 'already_running'}
    state['running'] = True
    try:
        token = os.getenv('THREADS_ACCESS_TOKEN', '').strip()
        if not token:
            raise SyncError('threads_token_missing')
        db = get_database()
        with requests.Session() as session:
            session.headers['Authorization'] = 'Bearer ' + token
            try:
                collect_followers(session, db, api_get)
                state['followers_error'] = None
            except (SyncError, GoogleAPICallError):
                state['followers_error'] = 'followers_collection_failed'
            state['progress'] = {'phase': 'posts', 'completed': 0, 'total': 0}
            rows = fetch_posts(session)
            documents = {}
            for row in rows:
                post_id = row.get('id', '')
                if not post_id.isascii() or not post_id.isdigit():
                    raise SyncError('threads_invalid_post_id')
                timestamp = datetime.fromisoformat(row['timestamp'])
                if timestamp.tzinfo is None:
                    raise SyncError('threads_invalid_timestamp')
                documents[post_id] = {
                    'id': post_id, 'text': row.get('text', ''), 'timestamp': timestamp,
                    'media_type': row['media_type'], 'permalink': row.get('permalink', ''),
                }
            if not documents:
                result = {'fetched': 0, 'created': 0, 'updated': 0, 'insights_saved': 0}
            else:
                refs = [db.collection('threads_posts').document(pid) for pid in documents]
                existing = {s.id: s for s in db.get_all(refs, timeout=30)}
                created = updated = saved = 0
                # Commit a post together with its initial insight. Retry incomplete reads
                # on later polls without replacing existing successful insights.
                state['progress'] = {'phase': 'posts', 'completed': 0, 'total': len(refs)}
                for position, ref in enumerate(refs, 1):
                    data = documents[ref.id]
                    snapshot = existing[ref.id]
                    check_insight = force or time.monotonic() >= next_insight_check.get(ref.id, 0)
                    latest = []
                    if check_insight and snapshot.exists:
                        latest = list(ref.collection('insights').order_by(
                            'collected_at', direction='DESCENDING'
                        ).limit(1).stream(timeout=10))
                    if not force and latest and latest[0].to_dict().get('status') == 'success':
                        age = (datetime.now(timezone.utc) - latest[0].to_dict()['collected_at']).total_seconds()
                        remaining = insight_interval_seconds() - age
                        if remaining > 0:
                            next_insight_check[ref.id] = time.monotonic() + remaining
                            check_insight = False
                    batch = db.batch()
                    changed = False
                    if not snapshot.exists:
                        batch.create(ref, data)
                        created += 1
                        changed = True
                    elif any(snapshot.to_dict().get(k) != v for k, v in data.items()):
                        batch.update(ref, data)
                        updated += 1
                        changed = True
                    if check_insight:
                        payload = api_get(session, f'{ref.id}/insights',
                                          {'metric': ','.join(METRICS)})
                        metrics = {name: None for name in METRICS}
                        for metric in payload['data']:
                            name = metric.get('name')
                            values = metric.get('values', [])
                            if name in metrics and values:
                                value = values[0].get('value')
                                if type(value) is int and value >= 0:
                                    metrics[name] = value
                        complete = all(v is not None for v in metrics.values())
                        # Avoid writing an identical empty observation every minute.
                        if complete or not latest:
                            now = datetime.now(timezone.utc)
                            insight_id = hashlib.sha256(now.isoformat().encode()).hexdigest()[:24]
                            insight_data = {
                                'post_id': ref.id, 'timestamp': data['timestamp'],
                                'collected_at': now, 'status': 'success' if complete else 'empty',
                                **metrics,
                            }
                            batch.create(ref.collection('insights').document(insight_id), insight_data)
                            record = observation(data, insight_data)
                            if record:
                                batch.set(db.collection('data').document('threads_' + ref.id), record, merge=True)
                            saved += 1
                            changed = True
                    if changed:
                        batch.commit(timeout=30)
                    if check_insight:
                        next_insight_check[ref.id] = time.monotonic() + (
                            insight_interval_seconds() if complete else interval_seconds()
                        )
                    state['progress'] = {'phase': 'posts', 'completed': position, 'total': len(refs), 'created': created}
                result = {'fetched': len(documents), 'created': created,
                          'updated': updated, 'insights_saved': saved}
            try:
                state['progress'] = {'phase': 'replies', 'completed': 0, 'total': 0}
                result['own_replies'] = sync_reply_views(session, db, api_get, insight_interval_seconds())
                state['replies_error'] = None
            except SyncError as exc:
                state['replies_error'] = str(exc)
                if str(exc) in ('threads_rate_limited', 'threads_token_expired_or_invalid'):
                    raise
            except (GoogleAPICallError, ValueError):
                state['replies_error'] = 'reply_collection_failed'
        state.update(last_success_at=datetime.now(timezone.utc).isoformat(),
                     last_error=None, last_result=result)
        return result
    except SyncError as exc:
        state['last_error'] = str(exc)
        raise
    except GoogleAPICallError:
        state['last_error'] = 'firestore_error'
        raise SyncError('firestore_error') from None
    except Exception:
        state['last_error'] = 'sync_internal_error'
        raise SyncError('sync_internal_error') from None
    finally:
        state['running'] = False
        lock.release()


def interval_seconds():
    try:
        return max(60, int(os.getenv('THREADS_SYNC_INTERVAL_SECONDS', '60')))
    except ValueError:
        return 60


def insight_interval_seconds():
    try:
        return max(300, int(os.getenv('THREADS_INSIGHT_INTERVAL_SECONDS', '900')))
    except ValueError:
        return 900


def enabled():
    return os.getenv('THREADS_AUTO_SYNC', 'false').lower() == 'true'


async def poll():
    while True:
        try:
            await asyncio.to_thread(sync_once)
        except SyncError as exc:
            logging.getLogger(__name__).warning('Threads sync failed: %s', exc)
        delay = interval_seconds()
        if state['last_error'] == 'threads_rate_limited':
            delay = max(delay, 900)
        elif state['last_error'] == 'threads_token_expired_or_invalid':
            delay = max(delay, 3600)
        await asyncio.sleep(delay)


def refresh_account_views():
    token = os.getenv('THREADS_ACCESS_TOKEN', '').strip()
    if not token:
        raise SyncError('threads_token_missing')
    with requests.Session() as session:
        session.headers['Authorization'] = 'Bearer ' + token
        reading = collect_account_views(session, get_database(), api_get)
    return reading['collected_at'].isoformat()


async def poll_account_views():
    # This worker runs independently of the slower per-post/reply insight scan.
    while True:
        delay = interval_seconds()
        try:
            observed = await asyncio.to_thread(refresh_account_views)
            state.update(account_views_last_success_at=observed, account_views_error=None)
        except SyncError as exc:
            state['account_views_error'] = str(exc)
            if str(exc) == 'threads_rate_limited':
                delay = max(delay, 900)
            elif str(exc) == 'threads_token_expired_or_invalid':
                delay = max(delay, 3600)
        except (ValueError, KeyError, TypeError):
            state['account_views_error'] = 'account_views_invalid_response'
        except Exception:
            state['account_views_error'] = 'account_views_collection_failed'
        await asyncio.sleep(delay)


@asynccontextmanager
async def lifespan(app):
    tasks = [asyncio.create_task(poll()), asyncio.create_task(poll_account_views())] if enabled() else []
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


@router.get('/status')
def sync_status():
    return {'enabled': enabled(), 'interval_seconds': interval_seconds(),
            'insight_interval_seconds': insight_interval_seconds(), **state,
            'manual': dict(manual_state)}


def run_manual_refresh(profile_snapshot=None, profile_error=None):
    errors, result = [], None
    if profile_snapshot is None:
        errors.append('profile_screen_unavailable')
    try:
        if profile_snapshot is not None:
            try:
                save_snapshot(get_database(), profile_snapshot)
            except Exception:
                errors.append('profile_save_failed')
        try:
            result = sync_once(force=True)
            if result.get('status') == 'already_running':
                errors.append('sync_already_running')
            for key in ('followers_error', 'replies_error'):
                if state.get(key):
                    errors.append(state[key])
        except SyncError as exc:
            errors.append(str(exc))
        try:
            state['progress'] = {'phase': 'account', 'completed': 0, 'total': 0}
            observed = refresh_account_views()
            state.update(account_views_last_success_at=observed, account_views_error=None)
        except SyncError as exc:
            errors.append(str(exc))
        except Exception:
            errors.append('account_views_collection_failed')
    except Exception:
        errors.append('sync_internal_error')
    finally:
        from app.chat_posts import clear_post_cache
        from app.read_cache import invalidate
        clear_post_cache()
        invalidate(retain=True)
        with manual_lock:
            manual_state.update(status='partial' if errors and result else 'failed' if errors else 'success',
                                result=result, errors=errors, profile_error=profile_error,
                                finished_at=datetime.now(timezone.utc).isoformat())


class ManualRefreshInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    profile_snapshot: ProfileSnapshot | None = None


@router.post('/run', status_code=202)
def start_manual_refresh(body: ManualRefreshInput | None = None):
    with manual_lock:
        if manual_state['status'] == 'running':
            return dict(manual_state)
        if state['running']:
            raise HTTPException(409, '현재 데이터를 업데이트 중입니다. 잠시 후 다시 시도해 주세요.')
        manual_state.update(status='running', started_at=datetime.now(timezone.utc).isoformat(),
                            finished_at=None, result=None, errors=[], profile_error=None)
        threading.Thread(target=run_manual_refresh,
                         kwargs={'profile_snapshot': body.profile_snapshot if body else None},
                         daemon=True).start()
        return dict(manual_state)
