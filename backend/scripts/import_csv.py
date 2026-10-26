"""Validate CSV files, then optionally create Firestore documents without overwrites."""
import argparse
import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

from app.database import get_database

METRICS = ('views', 'likes', 'replies', 'reposts', 'quotes')


def read_csv(path, required):
    with Path(path).open(encoding='utf-8-sig', newline='') as source:
        reader = csv.DictReader(source)
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f'Missing required columns in {Path(path).name}')
        rows = list(reader)
    if not rows:
        raise ValueError('CSV is empty')
    return rows


def parse_time(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError('Timestamp must include timezone')
    return result


def prepare(posts_path, insights_path):
    posts = read_csv(posts_path, {'id', 'text', 'timestamp', 'media_type', 'permalink'})
    insights = read_csv(insights_path, {'post_id', 'timestamp', 'text', 'media_type', 'status', 'collected_at', *METRICS})
    documents = {}
    post_ids = set()
    for row in posts:
        post_id = row['id']
        if not post_id.isascii() or not post_id.isdigit() or post_id in post_ids:
            raise ValueError('Invalid or duplicate post ID')
        post_ids.add(post_id)
        documents[f'threads_posts/{post_id}'] = {
            'id': post_id, 'text': row['text'], 'timestamp': parse_time(row['timestamp']),
            'media_type': row['media_type'], 'permalink': row['permalink'],
        }
    seen = set()
    for row in insights:
        post_id = row['post_id']
        if post_id not in post_ids:
            raise ValueError('Insight references an unknown post')
        collected_at = parse_time(row['collected_at'])
        snapshot_id = hashlib.sha256(collected_at.isoformat().encode()).hexdigest()[:24]
        path = f'threads_posts/{post_id}/insights/{snapshot_id}'
        if path in documents:
            raise ValueError('Duplicate insight snapshot')
        if row['status'] not in ('success', 'empty'):
            raise ValueError('Unexpected insight status')
        metrics = {}
        for name in METRICS:
            raw = row[name].strip()
            metrics[name] = int(raw) if raw else None
            if metrics[name] is not None and metrics[name] < 0:
                raise ValueError('Negative metric')
        if row['status'] == 'success' and any(v is None for v in metrics.values()):
            raise ValueError('Successful insight has missing metrics')
        documents[path] = {
            'post_id': post_id, 'timestamp': parse_time(row['timestamp']),
            'collected_at': collected_at, 'status': row['status'], **metrics,
        }
        seen.add(post_id)
    if seen != post_ids:
        raise ValueError('Some posts have no insight row')
    if len(documents) > 400:
        raise ValueError('Import exceeds the supported single-batch size (400 documents)')
    return documents, {'posts': len(posts), 'insight_snapshots': len(insights),
                       'empty_insights': sum(r['status'] == 'empty' for r in insights)}


def import_documents(db, documents, write=False):
    refs = [db.document(path) for path in documents]
    existing = {s.reference.path: s for s in db.get_all(refs, timeout=30)}
    pending = []
    for ref in refs:
        snapshot = existing[ref.path]
        if snapshot.exists:
            if snapshot.to_dict() != documents[ref.path]:
                raise ValueError(f'Existing document differs: {ref.path}; nothing overwritten')
        else:
            pending.append(ref)
    if write and pending:
        batch = db.batch()
        for ref in pending:
            batch.create(ref, documents[ref.path])
        batch.commit(timeout=30)
    if write:
        verified = list(db.get_all(refs, timeout=30))
        if len(verified) != len(documents) or any(
            not s.exists or s.to_dict() != documents[s.reference.path] for s in verified
        ):
            raise RuntimeError('Read-back verification failed')
    return {'created' if write else 'would_create': len(pending),
            'already_present': len(refs) - len(pending), 'verified': write}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--posts', required=True)
    parser.add_argument('--insights', required=True)
    parser.add_argument('--write', action='store_true', help='Actually write; otherwise read-only preview')
    args = parser.parse_args()
    documents, summary = prepare(args.posts, args.insights)
    summary.update(import_documents(get_database(), documents, args.write))
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
