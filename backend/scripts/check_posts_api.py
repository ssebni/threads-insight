"""Read-only API integration check against the configured Firestore database."""
import os
os.environ['THREADS_AUTO_SYNC'] = 'false'
from fastapi.testclient import TestClient
from google.api_core.exceptions import ServiceUnavailable

from app.main import app
from app.posts import database


def main():
    with TestClient(app) as client:
        assert client.get('/health').status_code == 200
        assert client.get('/docs').status_code == 200
        ids, timestamps = [], []
        cursor = None
        while True:
            params = {'limit': 25}
            if cursor:
                params['cursor'] = cursor
            response = client.get('/api/v1/posts', params=params)
            assert response.status_code == 200, response.text
            body = response.json()
            ids.extend(p['id'] for p in body['items'])
            timestamps.extend(p['timestamp'] for p in body['items'])
            if not body['has_more']:
                assert body['next_cursor'] is None
                break
            assert body['next_cursor'] != cursor
            cursor = body['next_cursor']
        assert len(ids) == len(set(ids)), 'Duplicate posts across pages'
        from datetime import datetime
        dates = [datetime.fromisoformat(t) for t in timestamps]
        assert dates == sorted(dates, reverse=True)
        assert ids, 'Expected imported posts'
        post = client.get(f'/api/v1/posts/{ids[0]}')
        assert post.status_code == 200
        detail = post.json()
        history = client.get(f'/api/v1/posts/{ids[0]}/insights')
        assert history.status_code == 200
        assert detail['latest_insight'] == history.json()['items'][0]
        first = client.get('/api/v1/posts', params={'limit': 1}).json()['items'][0]
        assert first['id'] == ids[0]
        if first['latest_insight']['status'] == 'empty':
            assert first['latest_insight']['views'] is None
        for params in ({'limit': 0}, {'limit': 101}, {'cursor': 'invalid'}):
            assert client.get('/api/v1/posts', params=params).status_code == 422
        assert client.get('/api/v1/posts/not-an-id').status_code == 422
        assert client.get('/api/v1/posts/0').status_code == 404
        assert client.get('/api/v1/posts/0/insights').status_code == 404
        assert client.get('/api/v1/posts?cursor=0').status_code == 400
        assert client.get(f'/api/v1/posts/{ids[0]}/insights?cursor=invalid').status_code == 422

        def unavailable():
            raise ServiceUnavailable('private database diagnostic')

        app.dependency_overrides[database] = unavailable
        try:
            failure = client.get('/api/v1/posts')
            assert failure.status_code == 503
            assert 'private' not in failure.text
        finally:
            app.dependency_overrides.clear()
    print(f'PASS: {len(ids)} unique posts; pagination, order, detail, insights, validation, 404/400/503')


if __name__ == '__main__':
    main()
