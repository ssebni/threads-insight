"""Collect only the authenticated account's own replies, independently of posts."""
from datetime import datetime, timezone
from app.sync_workers import collect_parallel


def fetch_replies(session, api_get):
    rows, after, seen = {}, None, set()
    for _ in range(100):
        params = {'fields': 'id,timestamp,media_type,permalink,is_reply', 'limit': 100}
        if after:
            params['after'] = after
        payload = api_get(session, 'me/replies', params)
        for row in payload['data']:
            if row.get('is_reply') is not True:
                continue
            pid = row.get('id', '')
            timestamp = datetime.fromisoformat(row['timestamp'])
            if not pid.isascii() or not pid.isdigit() or timestamp.tzinfo is None:
                raise ValueError('invalid_reply_metadata')
            rows[pid] = {'id': pid, 'timestamp': timestamp, 'is_reply': True,
                         'permalink': row.get('permalink', '')}
        paging = payload.get('paging', {})
        if not paging.get('next'):
            return rows
        after = paging.get('cursors', {}).get('after')
        if not after or after in seen:
            raise ValueError('invalid_reply_pagination')
        seen.add(after)
    raise ValueError('reply_page_limit_exceeded')


def sync_reply_views(session, db, api_get, interval, limit=40, progress=None):
    rows = fetch_replies(session, api_get)
    refs = [db.collection('threads_replies').document(pid) for pid in rows]
    existing = {s.id: s.to_dict() if s.exists else {} for s in db.get_all(refs, timeout=30)} if refs else {}
    now = datetime.now(timezone.utc)
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    # Oldest attempts first: even an unavailable insight cannot starve later replies.
    due = sorted(refs, key=lambda r: existing[r.id].get('checked_at', epoch))
    eligible = [ref for ref in due if (now - existing[ref.id].get('checked_at', epoch)).total_seconds() >= interval]
    selected = eligible[:limit]
    saved = checked = 0
    if progress:
        progress(0, len(selected))

    def collect(ref, worker_session):
        payload = api_get(worker_session, f'{ref.id}/insights', {'metric': 'views'})
        value = None
        for metric in payload['data']:
            values = metric.get('values', [])
            if metric.get('name') == 'views' and values:
                candidate = values[0].get('value')
                if type(candidate) is int and candidate >= 0:
                    value = candidate
        reading = {**rows[ref.id], 'checked_at': now}
        if value is not None:
            reading.update(views=value, collected_at=now)
        # Missing metrics retain the last successful value, never overwrite it with zero.
        ref.set(reading, merge=True, timeout=20)
        return value is not None

    for has_views in collect_parallel(selected, session, collect):
        saved += int(has_views)
        checked += 1
        if progress:
            progress(checked, len(selected))
    return {'fetched': len(rows), 'checked': checked, 'views_saved': saved,
            'pending': len(eligible) - checked}


def combined_views(posts_total, posts_coverage, posts_ids, replies):
    valid = [r for r in replies if r.get('is_reply') is True and r['id'] not in posts_ids
             and type(r.get('views')) is int and r['views'] >= 0]
    reply_total = sum(r['views'] for r in valid) if valid else None
    return {'total': (posts_total or 0) + (reply_total or 0) if posts_coverage or valid else None,
            'posts': posts_total, 'own_replies': reply_total,
            'posts_coverage': posts_coverage, 'own_replies_coverage': len(valid)}
