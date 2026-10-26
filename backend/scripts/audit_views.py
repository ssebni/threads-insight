"""Read-only numerical reconciliation of root-post, own-reply and account views."""
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests

from app.database import get_database


def main():
    metadata = json.loads(Path('work/views-audit-metadata.json').read_text(encoding='utf-8'))
    token = os.environ['THREADS_ACCESS_TOKEN']
    root = {row['id']: row for row in metadata['threads']['items']}
    replies = {row['id']: row for row in metadata['replies']['items']}
    items = {**root, **replies}
    stopped = threading.Event()

    def fetch(post_id):
        if stopped.is_set():
            return {'id': post_id, 'error': 'stopped_after_rate_limit'}
        try:
            r = requests.get(f'https://graph.threads.net/v1.0/{post_id}/insights',
                             headers={'Authorization': 'Bearer ' + token},
                             params={'metric': 'views'}, timeout=20)
            payload = r.json()
            if r.status_code == 429 or payload.get('error', {}).get('code') in (4, 32, 613):
                stopped.set()
            if r.status_code != 200:
                return {'id': post_id, 'error_code': payload.get('error', {}).get('code'),
                        'http_status': r.status_code}
            values = next((m.get('values', []) for m in payload.get('data', []) if m.get('name') == 'views'), [])
            value = values[0].get('value') if values else None
            return {'id': post_id, 'views': value, 'kind': 'post' if post_id in root else 'own_reply',
                    'observed_at': datetime.now(timezone.utc).isoformat()}
        except (requests.RequestException, ValueError):
            return {'id': post_id, 'error': 'network_or_response_error'}

    observed = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(fetch, post_id) for post_id in items]
        for future in as_completed(futures):
            observed.append(future.result())
            if len(observed) % 50 == 0:
                Path('work/views-audit-observations.json').write_text(json.dumps(observed, indent=2), encoding='utf-8')
                print(f'Checked {len(observed)}/{len(items)}', flush=True)
    Path('work/views-audit-observations.json').write_text(json.dumps(observed, indent=2), encoding='utf-8')
    totals = {}
    for kind in ('post', 'own_reply'):
        group = [row for row in observed if row.get('kind') == kind]
        known = [row for row in group if type(row.get('views')) is int]
        totals[kind] = {'retrieved': len(group), 'known': len(known),
                        'views': sum(row['views'] for row in known),
                        'empty_ids': [row['id'] for row in group if row.get('views') is None]}
    account = next(m for m in metadata['account_insights']['data'] if m['name'] == 'views')
    result = {'observed_at': datetime.now(timezone.utc).isoformat(),
              'metadata_complete': {name: metadata[name]['complete'] for name in ('threads', 'replies')},
              'overlap_ids': sorted(set(root) & set(replies)), 'totals': totals,
              'account_views': sum(v['value'] for v in account['values']),
              'account_daily': account['values'],
              'errors': [row for row in observed if 'error' in row or 'error_code' in row],
              'top_replies': sorted([row for row in observed if row.get('kind') == 'own_reply' and type(row.get('views')) is int],
                                    key=lambda row: row['views'], reverse=True)[:10]}
    result['combined_views'] = sum(group['views'] for group in totals.values())
    result['account_minus_combined'] = result['account_views'] - result['combined_views']
    Path('work/views-audit-result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
