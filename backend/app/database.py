import os
from functools import lru_cache
from pathlib import Path
from threading import Lock

import firebase_admin
from dotenv import load_dotenv
from firebase_admin import credentials, firestore

BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR / '.env')
_initialization_lock = Lock()


@lru_cache(maxsize=1)
def get_database():
    key_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS', '').strip()
    if not key_path:
        raise RuntimeError('GOOGLE_APPLICATION_CREDENTIALS is not configured')
    path = Path(key_path).expanduser()
    if not path.is_absolute():
        path = BACKEND_DIR / path
    if not path.is_file():
        raise RuntimeError('Service account file was not found')
    # Concurrent first requests can enter an lru_cache miss together.
    with _initialization_lock:
        try:
            app = firebase_admin.get_app('threads-insight')
        except ValueError:
            app = firebase_admin.initialize_app(
                credentials.Certificate(str(path)), name='threads-insight'
            )
    return firestore.client(
        app=app, database_id=os.getenv('FIRESTORE_DATABASE_ID', '(default)')
    )


def check_connection():
    # A missing document is a successful read, including for an empty database.
    snapshot = get_database().collection('_health').document('connection').get(
        timeout=10, retry=None
    )
    return {'status': 'ok', 'firestore': 'connected', 'document_exists': snapshot.exists}
