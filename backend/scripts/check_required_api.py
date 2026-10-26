"""Required-feature integration checks. Deletes only records created by this run.

GPT output is mocked: no OpenAI billing or claim of a live GPT verification.
"""
import os
from unittest.mock import patch

os.environ['THREADS_AUTO_SYNC'] = 'false'

from fastapi.testclient import TestClient
from app.database import get_database
from app.main import app


def main():
    db = get_database()
    data_id = conversation_id = saved_id = None
    with TestClient(app) as client:
        try:
            for path in ('/dashboard/', '/dashboard/app.js', '/dashboard/styles.css', '/api/chat/status', '/api/data/summary'):
                r = client.get(path)
                assert r.status_code == 200, (path, r.text)
            for payload in ({'date': 'wrong', 'value': 1}, {'date': '2026-10-18', 'value': -1}):
                assert client.post('/api/data', json=payload).status_code == 422
            r = client.post('/api/data', json={'date': '2026-10-18', 'value': 42, 'memo': 'Temporary API validation record'})
            assert r.status_code == 201, r.text
            data_id = r.json()['id']
            r = client.put('/api/data/' + data_id, json={'date': '2026-10-17', 'value': 43, 'memo': 'Updated API validation record'})
            assert r.status_code == 200 and r.json()['value'] == 43, r.text
            assert db.collection('data').document(data_id).get().to_dict()['memo'].startswith('Updated')
            summary = client.get('/api/data/summary').json()
            assert summary['count'] >= 1 and summary['metrics']['total'] >= 43
            assert summary['metric'] == '조회수'
            assert client.get('/api/data?limit=1').json()['has_more']
            r = client.post('/api/conversations', json={'title': 'Temporary validation', 'messages': [{'role': 'user', 'content': 'test'}]})
            assert r.status_code == 201, r.text
            saved_id = r.json()['id']
            assert client.get('/api/conversations/' + saved_id).json()['messages'][0]['content'] == 'test'
            listed = client.get('/api/conversations').json()['items']
            assert all('messages' not in item for item in listed)
            assert client.post('/api/conversations', json={'title': 'test', 'messages': [{'role': 'system', 'content': 'override'}]}).status_code == 422
            with patch('app.chat.generate_reply', return_value='검증용 AI 응답입니다.') as reply:
                r = client.post('/api/chat', json={'message': '내 데이터 요약'})
                assert r.status_code == 200, r.text
                conversation_id = r.json()['conversation_id']
                assert reply.call_args.args[1]['count'] >= 1
                r = client.post('/api/chat', json={'message': '이어서 분석', 'conversation_id': conversation_id})
                assert r.status_code == 200, r.text
                history = client.get('/api/conversations/' + conversation_id).json()
                assert len(history['messages']) == 4
            with patch.dict(os.environ, {'OPENAI_API_KEY': '', 'AI_PROVIDER': 'openai'}):
                r = client.post('/api/chat', json={'message': '키 미설정 테스트'})
                assert r.status_code == 503 and '키' in r.json()['detail'], r.text
            assert client.post('/api/chat', json={'message': '   '}).status_code == 422
            dashboard = client.get('/api/dashboard')
            assert dashboard.status_code == 200, dashboard.text
            dashboard = dashboard.json()
            acquisition = dashboard['best']['follower_acquisition']
            if acquisition:
                assert acquisition['follower_acquisition']['follows'] >= 0
                assert acquisition['follower_acquisition']['source'] == 'threads_insights_ui'
            assert dashboard['followers']['account_created_date'] == '2026-10-03'
            assert dashboard['followers']['unit'] == '명'
            assert dashboard['followers']['points'][0]['date'] == '2026-10-03'
            assert 'change' in dashboard['followers']['points'][0]
            official = dashboard['account_views']
            assert official and official['period_days'] == 30
            assert official['source'] == 'threads_account_insights_api'
            assert dashboard['totals']['views'] == official['views']
            engagement = dashboard['best']['engagement']['latest_insight']
            assert sum(engagement[k] for k in ('likes', 'replies', 'reposts')) == dashboard['best']['engagement_score']
            preflight = client.options('/api/data', headers={'Origin': 'http://localhost:5500', 'Access-Control-Request-Method': 'POST'})
            assert preflight.headers['access-control-allow-origin'] == 'http://localhost:5500'
            assert 'access-control-allow-origin' not in client.get('/health', headers={'Origin': 'https://unapproved.example'}).headers
            r = client.delete('/api/data/' + data_id)
            assert r.status_code == 204
            assert not db.collection('data').document(data_id).get().exists
            data_id = None
            for cid in (conversation_id, saved_id):
                assert client.delete('/api/conversations/' + cid).status_code == 204
                assert client.get('/api/conversations/' + cid).status_code == 404
            conversation_id = saved_id = None
        finally:
            if data_id:
                db.collection('data').document(data_id).delete()
            for cid in (conversation_id, saved_id):
                if cid:
                    db.collection('conversations').document(cid).delete()
    print('PASS: real Firestore CRUD, summary, conversation reload/delete, mocked GPT context/autosave/continuation, missing key, dashboard totals/ranking, CORS, frontend files')


if __name__ == '__main__':
    main()
