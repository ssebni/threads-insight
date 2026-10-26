"""Bounded post-level evidence for chat, separate from aggregate statistics."""
import re
import time
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from app.posts import serialize_post

_post_cache = {'at': 0, 'posts': None}


def clear_post_cache():
    _post_cache.update(at=0, posts=None)


def views_filter(question):
    # Only apply an unambiguous view condition; do not apply like/reply thresholds to views.
    match = re.search(r'조회수?\s*(?:가|는|이)?\s*([\d,]+(?:\.\d+)?)\s*(억|만|천)?\s*(?:회|뷰)?\s*(이상|초과|넘는|넘은|이하|미만)', question)
    if not match:
        return None
    value = int(Decimal(match[1].replace(',', '')) * {'억':100000000, '만':10000, '천':1000, None:1}[match[2]])
    return {'metric':'views', 'value':value, 'operator':match[3]}


def matches_views(value, condition):
    if type(value) is not int:
        return False
    target = condition['value']
    return {'이상':value >= target, '초과':value > target, '넘는':value > target,
            '넘은':value > target, '이하':value <= target, '미만':value < target}[condition['operator']]


def select_evidence(posts, question):
    ordered = sorted(posts, key=lambda post: (post.get('views') if post.get('views') is not None else -1,
                                             post['published_at'],post['id']), reverse=True)
    condition = views_filter(question)
    if condition:
        matches = [post for post in ordered if matches_views(post.get('views'), condition)]
        selected = matches[:40]
        selection = {'method':'views_condition','condition':condition,'matched_count':len(matches)}
    else:
        terms = re.findall(r'[가-힣A-Za-z0-9_]{2,}',question.casefold())
        stop = {'게시물','스레드','조회수','좋아요','댓글','리포스트','내용','분석','공통점','알려줘','어떤','최근','최고','이상','미만'}
        terms = [term for term in terms if term not in stop]
        relevant = sorted(ordered, key=lambda post:sum(term in post['text'].casefold() or term in post.get('permalink','').casefold() or term == post['id'] for term in terms), reverse=True)
        # Include high performers, recent posts and text matches; deduplicate by post ID.
        recent = sorted(posts,key=lambda post:(post['published_at'],post['id']),reverse=True)
        selected = list({post['id']:post for post in relevant[:20]+ordered[:10]+recent[:10]}.values())
        selection = {'method':'keyword_highest_views_recent','matched_count':None}
    details = [{**post,'text':post['text'][:1600], 'text_truncated':len(post['text'])>1600} for post in selected]
    index = [{key:value for key,value in post.items() if key not in ('text','permalink')} for post in ordered]
    return {'source':'stored_threads_posts_latest_insights','catalog_count':len(posts),
            'known_views_count':sum(type(post.get('views')) is int for post in posts),
            'index':index, 'selection':selection, 'details_count':len(details),'details':details,
            'scope_note':'index는 수집된 본문 게시물 전체의 최신 지표입니다. details만 원문을 포함합니다. 조건 일치가 40개를 초과하면 상위 40개 본문만 포함합니다. 형식은 API 메타데이터, 주제·톤은 본문을 근거로 해석하며 실제 노출 원인은 단정하지 않습니다. 현재 저장된 값이며 질문 시 Meta를 새로 수집하지 않습니다.'}


def post_evidence(db, messages):
    posts = _post_cache['posts']
    if posts is None or time.monotonic() - _post_cache['at'] >= 120:
        snapshots = list(db.collection('threads_posts').limit(501).stream(timeout=30))
        if len(snapshots)>500:
            raise HTTPException(503,'AI 게시물 분석 범위 500개를 초과했습니다. 분석 범위를 제한하도록 설정이 필요합니다.')
        posts=[]
        for snapshot in snapshots:
            if snapshot.to_dict().get('media_type','').upper()=='REPOST_FACADE':
                continue
            post=serialize_post(snapshot)
            insight=post.latest_insight
            posts.append({'id':post.id,'text':post.text,'published_at':post.timestamp.astimezone(ZoneInfo('Asia/Seoul')).isoformat(),
                          'media_type':post.media_type,'permalink':post.permalink,
                          **{key:getattr(insight,key) if insight else None for key in ('views','likes','replies','reposts')},
                          'observed_at':insight.collected_at.isoformat() if insight else None})
        _post_cache.update(at=time.monotonic(),posts=posts)
    question=messages[-1]['content']
    if not views_filter(question) and re.search(r'그\s*(?:글|게시물|스레드)|그중|그 중|이어서|걔네|공통점',question):
        prior=next((message['content'] for message in reversed(messages[:-1]) if message['role']=='user' and views_filter(message['content'])),None)
        if prior and not re.search(r'전체|모든',question):question=prior+'\n'+question
    return select_evidence(posts,question)
