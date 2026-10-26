"""Manually run one Threads sync without starting the web server."""
import json

from app.threads_sync import SyncError, sync_once


if __name__ == '__main__':
    try:
        print(json.dumps(sync_once()))
    except SyncError as exc:
        print(json.dumps({'status': 'failed', 'reason': str(exc)}))
        raise SystemExit(1)
