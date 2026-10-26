"""Interactive local launcher with visible startup checks and a persistent log."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import uuid
import time
from urllib.error import URLError
from urllib.request import build_opener, ProxyHandler
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
HOST, PORT = '127.0.0.1', 8010
URL = f'http://{HOST}:{PORT}'
LOG = ROOT / 'work' / 'launcher.log'
OPENER = build_opener(ProxyHandler({}))


def healthy():
    try:
        with OPENER.open(URL + '/health', timeout=2) as response:
            data = json.load(response)
        return data.get('status') == 'ok' and data.get('service') == 'threads-insight-api'
    except (URLError, OSError, ValueError):
        return False


def port_available():
    try:
        with socket.socket() as probe:
            probe.bind((HOST, PORT))
        return True
    except OSError:
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--diagnose', action='store_true')
    parser.add_argument('--gui', action='store_true')
    parser.add_argument('--stop', action='store_true')
    parser.add_argument('--restart', action='store_true')
    args = parser.parse_args()
    if args.stop:
        return stop_background_server()
    if args.restart and healthy():
        result = stop_background_server()
        if result:
            return result
    print('THREADS INSIGHT - background server startup', flush=True)
    print('Project: ' + str(ROOT), flush=True)
    print('Dashboard: ' + URL + '/dashboard/', flush=True)
    missing = [name for name in ('uvicorn', 'fastapi', 'firebase_admin') if importlib.util.find_spec(name) is None]
    if missing:
        print('ERROR: Missing packages: ' + ', '.join(missing), flush=True)
        return 1
    print('Python and required packages: OK', flush=True)
    if healthy():
        print('Server is already responding on port 8010.', flush=True)
        if not args.diagnose:
            webbrowser.open(URL + '/dashboard/')
        return 0
    available = port_available()
    print('Port 8010: ' + ('available' if available else 'IN USE, but health check failed'), flush=True)
    if not available:
        print('ERROR: Existing process occupies port 8010 (10048).', flush=True)
        print('Close the previous Threads server with Ctrl+C, then run this file again.', flush=True)
        return 2
    if args.diagnose:
        print('Diagnostics complete. Server was not started.', flush=True)
        return 0
    LOG.parent.mkdir(parents=True, exist_ok=True)
    print('Starting background server. Log: ' + str(LOG), flush=True)
    instance = uuid.uuid4().hex
    env = {**os.environ, 'PYTHONUNBUFFERED': '1', 'PYTHONUTF8': '1'}
    server = spawn_background(instance, env)
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if server.poll() is not None:
            print('ERROR: Server exited. See ' + str(LOG), flush=True)
            return server.returncode or 1
        if healthy():
            print('READY: ' + URL + '/dashboard/', flush=True)
            print('Server runs in the background. You may close this window.', flush=True)
            print('To stop it, run stop-dashboard.cmd.', flush=True)
            webbrowser.open(URL + '/dashboard/')
            return 0
        time.sleep(0.5)
    print('ERROR: Startup could not be confirmed. See ' + str(LOG), flush=True)
    print('The background process was not automatically terminated.', flush=True)
    return 3


def spawn_background(instance, env):
    options = {'creationflags': subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
    with LOG.open('a', encoding='utf-8') as log:
        log.write('\n--- Detached server startup ---\n'); log.flush()
        return subprocess.Popen([sys.executable, '-u', str(ROOT / 'scripts' / 'run_local_server.py'),
                                 '--instance', instance], cwd=ROOT, env=env,
                                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                close_fds=True, **options)


def stop_background_server():
    from run_local_server import STATE, CONTROL, read_json, write_json
    state = read_json(STATE)
    if not state.get('instance') or state.get('status') != 'running':
        print('No background server started by this launcher was found.', flush=True)
        print('If an older server window is open, stop it with Ctrl+C.', flush=True)
        return 1
    write_json(CONTROL, {'instance': state['instance'], 'command': 'stop'})
    print('Graceful shutdown requested for this project server.', flush=True)
    for _ in range(60):
        current = read_json(STATE)
        if current.get('instance') != state['instance'] or current.get('status') == 'stopped':
            print('Server stopped.', flush=True)
            return 0
        time.sleep(0.5)
    print('Shutdown is still pending. See ' + str(LOG), flush=True)
    return 2

if __name__ == '__main__':
    gui = '--gui' in sys.argv
    if gui or sys.stdout is None:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        sys.stdout = (LOG.parent / 'launcher-ui.log').open('a', encoding='utf-8', buffering=1)
        sys.stderr = sys.stdout
    else:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    try:
        exit_code = main()
    except Exception:
        import traceback
        traceback.print_exc()
        exit_code = 1
    if gui and exit_code:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None,
            'Server startup failed. Please share the log at:\n' + str(LOG.parent / 'launcher-ui.log'),
            'Threads Insight', 0x10)
    raise SystemExit(exit_code)

