"""Detached local server with a project-scoped graceful stop signal."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import threading

import uvicorn

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / 'work' / 'local-server-instance.json'
CONTROL = ROOT / 'work' / 'local-server-control.json'


def read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def write_json(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


def watch_stop(server, instance, finished):
    while not finished.wait(0.25):
        signal = read_json(CONTROL)
        if signal.get('instance') == instance and signal.get('command') == 'stop':
            server.should_exit = True
            return


def main():
    import os
    parser = argparse.ArgumentParser()
    parser.add_argument('--instance', required=True)
    instance = parser.parse_args().instance
    sys.path.insert(0, str(ROOT))
    STATE.parent.mkdir(parents=True, exist_ok=True)
    if sys.stdout is None:
        sys.stdout = (STATE.parent / 'launcher.log').open('a', encoding='utf-8', buffering=1)
    if sys.stderr is None:
        sys.stderr = sys.stdout
    info = {'instance': instance, 'pid': os.getpid(), 'mode': 'background',
            'started_at': datetime.now(timezone.utc).isoformat(), 'status': 'running'}
    write_json(STATE, info)
    finished = threading.Event()
    server = uvicorn.Server(uvicorn.Config('app.main:app', host='127.0.0.1', port=8010))
    watcher = threading.Thread(target=watch_stop, args=(server, instance, finished), daemon=True)
    watcher.start()
    try:
        server.run()
    finally:
        finished.set()
        if read_json(STATE).get('instance') == instance:
            write_json(STATE, {**info, 'status': 'stopped', 'stopped_at': datetime.now(timezone.utc).isoformat()})

if __name__ == '__main__':
    main()
