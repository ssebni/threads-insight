"""Offline contract checks: no network or real Firestore writes."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from pydantic import ValidationError
from app.profile_snapshot import ProfileSnapshot, save_snapshot
from app import threads_sync as sync


def payload():
    return {'profile': {'account_username': 'nibetsi.zip',
            'source_url': 'https://www.threads.com/@nibetsi.zip', 'source': 'threads_profile_ui',
            'followers_count': 259, 'observed_at': datetime.now(timezone.utc)},
            'views_label': '최근 조회수 338.3만회'}


reading = ProfileSnapshot.model_validate(payload())
for change in ('stale', 'account', 'negative', 'label', 'naive'):
    data = payload()
    if change == 'stale': data['profile']['observed_at'] -= timedelta(minutes=6)
    if change == 'account': data['profile']['account_username'] = 'someone_else'
    if change == 'negative': data['profile']['followers_count'] = -1
    if change == 'label': data['views_label'] = '최근 조회수 ...회'
    if change == 'naive': data['profile']['observed_at'] = datetime.now()
    try:
        ProfileSnapshot.model_validate(data)
    except ValidationError:
        continue
    raise AssertionError('Accepted invalid observation: ' + change)

db = MagicMock()
db.collection.return_value.document.return_value.get.return_value.exists = False
with patch('app.profile_snapshot.firestore.transactional', lambda fn: fn):
    save_snapshot(db, reading)
assert db.transaction.return_value.set.call_count == 4
values = [call.args[1] for call in db.transaction.return_value.set.call_args_list]
assert any(value.get('display_value') == '338.3만' for value in values)
assert any(value.get('followers_count') == 259 for value in values)
assert all('views' not in value for value in values)  # Never infer an exact count.

db.collection.return_value.document.return_value.get.return_value.exists = True
db.collection.return_value.document.return_value.get.return_value.to_dict.return_value = {
    'observed_at': reading.profile.observed_at + timedelta(seconds=1)}
db.transaction.return_value.set.reset_mock()
with patch('app.profile_snapshot.firestore.transactional', lambda fn: fn):
    try: save_snapshot(db, reading)
    except ValueError: pass
    else: raise AssertionError('Overwrote a newer observation')
assert not db.transaction.return_value.set.called

sync.state.update(followers_error=None, replies_error=None)
with patch.object(sync, 'sync_once', return_value={'created': 1}), \
     patch.object(sync, 'refresh_account_views', return_value='verified'), \
     patch.object(sync, 'save_snapshot') as save, patch.object(sync, 'get_database'):
    sync.run_manual_refresh(reading)
    assert sync.manual_state['status'] == 'success'
    save.assert_called_once()
    save.reset_mock()
    sync.run_manual_refresh()
    assert sync.manual_state['status'] == 'partial'
    assert 'profile_screen_unavailable' in sync.manual_state['errors']
    assert not save.called
    save.side_effect = RuntimeError('offline')
    sync.run_manual_refresh(reading)
    assert 'profile_save_failed' in sync.manual_state['errors']
print('PASS: validation, display precision, monotonic writes, successful and partial refresh')
