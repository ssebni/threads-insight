"""Read-only coverage and 30-day window checks; retain the original audit snapshot."""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from app.database import get_database


def main():
    metadata = json.loads(Path('work/views-audit-metadata.json').read_text(encoding='utf-8'))
    result = json.loads(Path('work/views-audit-result.json').read_text(encoding='utf-8'))
    roots = {p['id']: p for p in metadata['threads']['items']}
    replies = {p['id']: p for p in metadata['replies']['items']}
    stored = {s.id for s in get_database().collection('threads_posts').stream(timeout=15, retry=None)}
    result['database_root_coverage_complete'] = set(roots) == stored
    result['root_ids_missing_in_database'] = sorted(set(roots) - stored)
    result['reply_flags_true'] = sum(p.get('is_reply') is True for p in replies.values())
    result['root_reply_flags_true'] = sum(p.get('is_reply') is True for p in roots.values())
    result['missing_root_types'] = [
        {'id': pid, 'media_type': roots[pid]['media_type']}
        for pid in result['totals']['post']['empty_ids']
    ]
    now = datetime.now(timezone.utc)
    response = requests.get(
        'https://graph.threads.net/v1.0/me/threads_insights',
        headers={'Authorization': 'Bearer ' + os.environ['THREADS_ACCESS_TOKEN']},
        params={'metric': 'views', 'since': int((now - timedelta(days=30)).timestamp()),
                'until': int(now.timestamp())}, timeout=25,
    )
    payload = response.json()
    response.raise_for_status()
    metric = next(m for m in payload['data'] if m['name'] == 'views')
    result['account_last_30_days_recheck'] = {
        'observed_at': now.isoformat(), 'views': sum(v['value'] for v in metric['values']),
        'daily': metric['values'],
    }
    result['relative_residual_percent'] = abs(result['account_minus_combined']) / result['account_views'] * 100
    result['top_reply_links'] = [
        {'permalink': replies[row['id']]['permalink'], 'views': row['views']}
        for row in result['top_replies'][:3]
    ]
    result['snapshot_started_at'] = metadata['observed_at']
    result['oldest_post'] = min(p['timestamp'] for p in roots.values())
    result['oldest_reply'] = min(p['timestamp'] for p in replies.values())
    Path('work/views-audit-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: result[k] for k in (
        'database_root_coverage_complete', 'root_ids_missing_in_database', 'reply_flags_true',
        'root_reply_flags_true', 'missing_root_types', 'relative_residual_percent',
        'snapshot_started_at', 'oldest_post', 'oldest_reply', 'top_reply_links',
    )}, ensure_ascii=False))
    print(json.dumps({'last_30_day_recheck': result['account_last_30_days_recheck']['views'],
                      'recheck_at': now.isoformat()}))


if __name__ == '__main__':
    main()
