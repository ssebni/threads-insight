"""Offline checks for post-level selection and exact view thresholds."""
from unittest.mock import MagicMock, patch
from datetime import datetime,timezone
from app.chat_posts import select_evidence, views_filter, post_evidence
from app.chat import generate_reply

def post(identity,views,text='협업 글'):
    return {'id':str(identity),'text':text,'published_at':'2026-10-26T12:00:00+09:00','media_type':'TEXT_POST',
            'permalink':'https://www.threads.com/@nibetsi.zip/post/example','views':views,
            'likes':0,'replies':0,'reposts':None,'observed_at':'2026-10-26T04:00:00+00:00'}

posts=[post(1,50000,'호주 여행 질문'),post(2,49999),post(3,None),post(4,70000,'카페 알바 이야기')]
result=select_evidence(posts,'조회수 5만 이상 게시물의 공통점')
assert result['selection']['matched_count']==2
assert {row['id'] for row in result['details']}=={'1','4'}
assert result['catalog_count']==4 and result['known_views_count']==3
assert result['details'][0]['reposts'] is None
assert views_filter('조회수 50,000회 초과')['value']==50000
assert views_filter('조회수 5.5만 이상')['value']==55000
assert views_filter('좋아요 100 이상') is None
assert select_evidence(posts,'조회수 5만 초과')['selection']['matched_count']==1
assert select_evidence(posts,'조회수 10만 이상')['details']==[]
assert select_evidence(posts,'조회수 5만 미만')['selection']['matched_count']==1
many=select_evidence([post(i,50000,'원문'*1000) for i in range(45)],'조회수 5만 이상')
assert many['selection']['matched_count']==45 and many['details_count']==40
assert all(row['text_truncated'] and len(row['text'])==1600 for row in many['details'])
keywords=select_evidence([post(i,100000-i,'호주' if i==70 else '일상') for i in range(80)],'호주')
assert '70' in [row['id'] for row in keywords['details']]
with patch('app.chat.codyssey_reply',return_value='테스트') as reply, patch('app.chat.chat_status',return_value={'provider':'codyssey_anthropic'}):
    generate_reply([{'role':'user','content':'조회수 5만 이상 게시물은?'}],{'count':4,'post_evidence':result})
    prompt=reply.call_args.args[1]
    assert '호주 여행 질문' in prompt and '카페 알바 이야기' in prompt and '70000' in prompt
print('PASS: >= vs >, decimal/comma thresholds, unknowns, exact counts, detail caps, keyword retrieval, prompt injection')
