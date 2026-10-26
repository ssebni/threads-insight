"""Import already verified own-reply audit readings without replacing newer polls."""
import json
from datetime import datetime
from pathlib import Path
from app.database import get_database


def main():
    root = Path(__file__).resolve().parents[1]
    metadata = json.loads((root / 'work/views-audit-metadata.json').read_text(encoding='utf-8'))
    if metadata['replies']['complete'] is not True:
        raise ValueError('Incomplete audit')
    rows = {r['id']: r for r in metadata['replies']['items'] if r.get('is_reply') is True}
    readings = json.loads((root / 'work/views-audit-observations.json').read_text(encoding='utf-8'))
    db = get_database()
    prepared = []
    for r in readings:
        if r['kind'] != 'own_reply':
            continue
        pid, value = r['id'], r['views']
        if pid not in rows or not pid.isascii() or not pid.isdigit():
            raise ValueError('Unmatched reply')
        if type(value) is not int or value < 0:
            continue
        observed = datetime.fromisoformat(r['observed_at'])
        timestamp = datetime.fromisoformat(rows[pid]['timestamp'])
        if observed.tzinfo is None or timestamp.tzinfo is None:
            raise ValueError('Missing timezone')
        prepared.append((pid, {'id': pid, 'is_reply': True, 'timestamp': timestamp,
                         'permalink': rows[pid]['permalink'], 'views': value,
                         'collected_at': observed, 'checked_at': observed}))
    saved = 0
    # Transaction prevents the running poller from losing a newer observation.
    from google.cloud import firestore
    @firestore.transactional
    def write(transaction, ref, data):
        old = ref.get(transaction=transaction)
        previous = old.to_dict() if old.exists else {}
        if previous.get('collected_at') and previous['collected_at'] >= data['collected_at']:
            return False
        transaction.set(ref, data, merge=True)
        return True
    for pid, data in prepared:
        saved += write(db.transaction(), db.collection('threads_replies').document(pid), data)
    print({'verified_replies': len(prepared), 'imported': saved})

if __name__ == '__main__':
    main()
