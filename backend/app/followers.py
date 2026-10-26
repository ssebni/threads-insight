from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def collect_followers(session, db, api_get):
    payload = api_get(session, 'me/threads_insights', {'metric': 'followers_count'})
    metric = next((m for m in payload['data'] if m.get('name') == 'followers_count'), {})
    value = metric.get('total_value', {}).get('value')
    if value is None and metric.get('values'):
        value = metric['values'][-1].get('value')
    if type(value) is not int or value < 0:
        return False
    now = datetime.now(timezone.utc)
    day = now.astimezone(ZoneInfo('Asia/Seoul')).date().isoformat()
    db.collection('follower_daily').document(day).set({
        'date': day, 'followers_count': value, 'observed_at': now,
    }, timeout=10)
    return True
