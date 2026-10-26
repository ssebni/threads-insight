"""Meta account-level views are authoritative for the recent-30-day headline."""
from datetime import datetime, timedelta, timezone


def parse_account_views(payload):
    metrics = [m for m in payload['data'] if m.get('name') == 'views']
    if len(metrics) != 1 or not metrics[0].get('values'):
        raise ValueError('account_views_unavailable')
    days, seen = [], set()
    for row in metrics[0]['values']:
        value = row.get('value')
        end = datetime.fromisoformat(row['end_time'])
        if type(value) is not int or value < 0 or end.tzinfo is None or end in seen:
            raise ValueError('account_views_invalid_response')
        seen.add(end)
        days.append({'value': value, 'end_time': end})
    return sum(r['value'] for r in days), days


def collect_account_views(session, db, api_get):
    requested_at = datetime.now(timezone.utc)
    start = requested_at - timedelta(days=30)
    params = {'metric': 'views', 'since': int(start.timestamp()),
              'until': int(requested_at.timestamp())}
    payload = api_get(session, 'me/threads_insights', params)
    value, daily = parse_account_views(payload)
    reading = {'views': value, 'source': 'threads_account_insights_api',
               'period_days': 30, 'window_start': start, 'window_end': requested_at,
               'collected_at': datetime.now(timezone.utc), 'daily': daily}
    # Validate the whole response first; errors must not replace the last good value.
    db.collection('account_insights').document('views_30d').set(reading, timeout=15)
    return reading


def read_account_views(db):
    snapshot = db.collection('account_insights').document('views_30d').get(timeout=10)
    data = snapshot.to_dict() if snapshot.exists else None
    if not data or type(data.get('views')) is not int or data['views'] < 0 or data.get('period_days') != 30:
        return None
    collected = data.get('collected_at')
    if not isinstance(collected, datetime) or collected.tzinfo is None:
        return None
    age = max(0, (datetime.now(timezone.utc) - collected).total_seconds())
    return {**data, 'age_seconds': round(age), 'stale': age > 180}
