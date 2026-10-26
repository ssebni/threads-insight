"""Offline checks: polling pagination, redacted errors, lifecycle, interval bounds."""
import os
import unittest
from unittest.mock import Mock, patch

os.environ['THREADS_AUTO_SYNC'] = 'false'

from fastapi.testclient import TestClient
from app.main import app
from app.threads_sync import SyncError, api_get, fetch_posts, interval_seconds, sync_once


class SyncChecks(unittest.TestCase):
    def test_pagination(self):
        session = Mock()
        session.get.side_effect = [
            Mock(status_code=200, json=lambda: {'data': [{'id': '1'}], 'paging': {
                'next': 'https://untrusted.example/?access_token=private',
                'cursors': {'after': 'abc'}}}),
            Mock(status_code=200, json=lambda: {'data': [{'id': '2'}]}),
        ]
        self.assertEqual(len(fetch_posts(session)), 2)
        self.assertEqual(session.get.call_args.kwargs['params']['after'], 'abc')
        self.assertTrue(all(c.args[0].startswith('https://graph.threads.net/')
                            for c in session.get.call_args_list))

    def test_redacted_token_failure(self):
        session = Mock()
        session.get.return_value = Mock(status_code=400, json=lambda: {
            'error': {'code': 190, 'message': 'private secret token'}})
        with self.assertRaisesRegex(SyncError, '^threads_token_expired_or_invalid$'):
            api_get(session, 'me/threads', {})

    def test_missing_token_no_database_write(self):
        with patch.dict(os.environ, {'THREADS_ACCESS_TOKEN': ''}):
            with patch('app.threads_sync.get_database') as db:
                with self.assertRaisesRegex(SyncError, 'threads_token_missing'):
                    sync_once()
                db.assert_not_called()

    def test_minimum_interval(self):
        with patch.dict(os.environ, {'THREADS_SYNC_INTERVAL_SECONDS': '1'}):
            self.assertEqual(interval_seconds(), 60)

    def test_disabled_lifecycle_and_status(self):
        with patch('app.threads_sync.poll') as poll:
            with TestClient(app) as client:
                response = client.get('/api/v1/sync/status')
                self.assertEqual(response.status_code, 200)
                self.assertFalse(response.json()['enabled'])
                self.assertNotIn('THREADS_ACCESS_TOKEN', response.text)
            poll.assert_not_called()


if __name__ == '__main__':
    unittest.main()
