"""Bounded I/O workers with a separate reusable HTTP session per thread."""
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

import requests

SYNC_WORKERS = 4


def collect_parallel(items, session, collect):
    """Yield completed results; stop queuing work on any API/database failure.

    At most four items are in flight. Sessions are never shared between workers,
    and remaining requests are allowed to finish before closing their sessions.
    """
    local = threading.local()
    sessions = []

    def run(item):
        if not hasattr(local, 'session'):
            local.session = requests.Session()
            local.session.headers.update(dict(session.headers))
            sessions.append(local.session)
        return collect(item, local.session)

    iterator = iter(items)
    pool = ThreadPoolExecutor(max_workers=SYNC_WORKERS, thread_name_prefix='threads-sync')
    pending = set()
    try:
        for _ in range(SYNC_WORKERS):
            item = next(iterator, None)
            if item is None:
                break
            pending.add(pool.submit(run, item))
        while pending:
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            # Check all completed tasks before scheduling more on a failed batch.
            results = [future.result() for future in done]
            for result in results:
                yield result
            for _ in done:
                item = next(iterator, None)
                if item is None:
                    break
                pending.add(pool.submit(run, item))
    finally:
        for future in pending:
            future.cancel()
        pool.shutdown(wait=True, cancel_futures=True)
        for worker_session in sessions:
            worker_session.close()
