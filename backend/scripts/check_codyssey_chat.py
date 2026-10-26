"""Offline provider contract tests. Never calls a real model or prints a key."""
import os
from unittest.mock import MagicMock, patch

import requests
from fastapi import HTTPException
from app.chat import generate_reply, chat_status

messages = [{'role':'user','content':'데이터를 요약해 줘'}]
summary = {'count':123,'unit':'회','daily':[{'date':'2026-10-26','value':1}]}
settings = {'AI_PROVIDER':'codyssey_anthropic','CODESEI_API_KEY':'offline-test-key',
            'CODESEI_BASE_URL':'https://copa.codyssey.kr','CODESEI_MODEL':'claude-sonnet-4'}
with patch.dict(os.environ, settings), patch('app.chat.requests.post') as post:
    response = MagicMock(status_code=200)
    response.json.return_value={'content':[{'type':'thinking','thinking':'hidden'}, {'type':'text','text':'123개 기록입니다.'}]}
    post.return_value=response
    assert chat_status()['configured'] is True
    assert generate_reply(messages,summary)=='123개 기록입니다.'
    args=post.call_args
    assert args.args[0]=='https://copa.codyssey.kr/v1/messages'
    assert args.kwargs['allow_redirects'] is False
    assert args.kwargs['headers']['anthropic-version']=='2023-06-01'
    body=args.kwargs['json']
    assert body['model']=='claude-sonnet-4' and body['max_tokens']==1000
    assert '123' in body['system'] and 'daily' not in body['system']
    assert body['messages']==messages and 'system' not in [m['role'] for m in body['messages']]
    for remote,expected in [(401,503),(403,503),(429,429),(500,502),(302,502)]:
        response.status_code=remote
        try:generate_reply(messages,summary)
        except HTTPException as error:assert error.status_code==expected
        else:raise AssertionError('Unexpected success')
    response.status_code=200
    for malformed in ({'content':[]}, {'content':'wrong'}, []):
        response.json.return_value=malformed
        try:generate_reply(messages,summary)
        except HTTPException as error:assert error.status_code==502
        else:raise AssertionError('Invalid content accepted')
    post.side_effect=requests.Timeout()
    try:generate_reply(messages,summary)
    except HTTPException as error:assert error.status_code==504
    else:raise AssertionError('Timeout accepted')
with patch.dict(os.environ,{**settings,'CODESEI_BASE_URL':'https://elsewhere.example'}), patch('app.chat.requests.post') as post:
    try:generate_reply(messages,summary)
    except HTTPException as error:assert error.status_code==503
    else:raise AssertionError('Untrusted host accepted')
    post.assert_not_called()
print('PASS: context injection, Anthropic protocol, content parsing, safe endpoint, errors')
