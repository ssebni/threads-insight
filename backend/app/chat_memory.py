"""Retrieve saved question/answer pairs without treating old answers as facts."""
import hashlib
import re
import threading
import time
import unicodedata
from difflib import SequenceMatcher
from decimal import Decimal

from app.chat_posts import views_filter

_lock = threading.RLock()
_cache = {'at': 0, 'db': None, 'pairs': None}
HISTORY_LIMIT = 200


def normalize_question(text):
    text = unicodedata.normalize('NFKC', text).casefold().strip()
    return re.sub(r'\s+', '', text).rstrip('?!.~？！。')


def question_key(text):
    return hashlib.sha256(normalize_question(text).encode()).hexdigest()


def clear_answer_memory():
    with _lock:
        _cache.update(at=0, db=None, pairs=None)


def contextual(question):
    return bool(re.search(r'그\s*(?:글|게시물|스레드|중|거|것|답변)|이\s*(?:글|게시물|답변)|이어서|방금|아까|앞서|이전 답변', question)) or len(normalize_question(question)) < 6


def context_key(messages):
    return hashlib.sha256(repr([(m['role'], normalize_question(m['content'])) for m in messages[-12:]]).encode()).hexdigest()


def saved_pairs(db):
    with _lock:
        if _cache['db'] is db and _cache['pairs'] is not None and time.monotonic()-_cache['at'] < 120:
            return _cache['pairs']
        snapshots = list(db.collection('conversations').order_by('updated_at', direction='DESCENDING')
                         .limit(HISTORY_LIMIT).stream(timeout=15))
        pairs = []
        for snapshot in snapshots:
            row = snapshot.to_dict()
            messages = row.get('messages', [])
            for index in range(len(messages)-2, -1, -1):
                question, answer = messages[index:index+2]
                if question.get('role') != 'user' or answer.get('role') != 'assistant':
                    continue
                if not isinstance(question.get('content'), str) or not isinstance(answer.get('content'), str) or not answer['content'].strip():
                    continue
                pairs.append({'conversation_id': snapshot.id, 'message_index': index+1,
                              'question': question['content'], 'answer': answer['content'],
                              'saved_at': answer.get('answered_at') or row.get('updated_at'),
                              'key': normalize_question(question['content']),
                              'context': context_key(messages[:index])})
        _cache.update(at=time.monotonic(), db=db, pairs=pairs)
        return pairs


def constraints(question):
    # Similar wording with different thresholds/metrics must not share references.
    values = tuple(sorted(str(Decimal(n.replace(',', '')) * {'':1, '천':1000, '만':10000, '억':100000000}[unit])
                          for n, unit in re.findall(r'(\d[\d,]*(?:\.\d+)?)\s*(천|만|억)?', question)))
    metrics = tuple(sorted(name for name, pattern in {
        'views':r'조회|노출', 'likes':r'좋아요', 'replies':r'댓글|답글',
        'reposts':r'리포스트|재게시', 'followers':r'팔로워|팔로우|유입', 'revenue':r'원고료|수익|수입',
    }.items() if re.search(pattern, question)))
    condition = views_filter(question)
    operator = ({'이상':'>=', '초과':'>', '넘는':'>', '넘은':'>', '이하':'<=', '미만':'<'}[condition['operator']]
                if condition else None)
    return values, metrics, operator


def similar_text(question):
    text = normalize_question(question)
    for source, target in [('게시글','게시물'), ('포스팅','게시물'), ('스레드','게시물'),
                           ('공통적인특징','공통점'), ('공통특징','공통점'), ('알려주세요','알려줘')]:
        text = text.replace(source,target)
    return text


def reference(pair):
    result = {key: pair[key] for key in ('conversation_id','message_index','question','saved_at')}
    saved_at = result['saved_at']
    result['saved_at'] = saved_at.isoformat() if hasattr(saved_at, 'isoformat') else saved_at
    return result


def recall(db, question, previous, conversation_id=None):
    key = normalize_question(question)
    context = context_key(previous)
    needs_context = contextual(question)
    candidates = [pair for pair in saved_pairs(db)
                  if not needs_context or (pair['conversation_id']==conversation_id and pair['context']==context)]
    exact = next((pair for pair in candidates if pair['key']==key), None)
    if exact:
        return exact, []
    current_constraints = constraints(question)
    similar = []
    seen = set()
    for pair in candidates:
        if pair['key'] in seen or constraints(pair['question']) != current_constraints:
            continue
        score = SequenceMatcher(None, similar_text(question), similar_text(pair['question']), autojunk=False).ratio()
        if score >= 0.65:
            similar.append({**pair,'similarity':round(score,3)})
            seen.add(pair['key'])
    return None, sorted(similar, key=lambda pair:pair['similarity'], reverse=True)[:3]
