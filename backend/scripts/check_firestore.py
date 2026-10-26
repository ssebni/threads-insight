"""Run from backend: python -m scripts.check_firestore"""
import json
import sys

from google.api_core.exceptions import GoogleAPICallError
from google.auth.exceptions import GoogleAuthError

from app.database import check_connection


def main():
    try:
        result = check_connection()
    except (RuntimeError, ValueError, OSError):
        print('FAIL: Check .env and the service account JSON file path.')
        return 1
    except (GoogleAPICallError, GoogleAuthError):
        print('FAIL: Check credentials, Firestore database ID, IAM permissions, and network access.')
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())
