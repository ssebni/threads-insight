"""Private collaboration labels, contract fees and observed post performance."""
import hashlib
import re
import unicodedata
from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from google.cloud import firestore
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.posts import database, require_post, PostId

router = APIRouter(prefix='/api/collaborations', tags=['collaborations'])


class ContractInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    tag: str
    date: date
    fee_mode: Literal['bundle', 'per_post'] = 'bundle'
    fee: int = Field(strict=True, ge=0, le=10**12)
    paid_amount: int = Field(default=0, strict=True, ge=0, le=10**12)
    memo: str = Field(default='', max_length=2000)

    @field_validator('tag')
    @classmethod
    def valid_tag(cls, value):
        value = unicodedata.normalize('NFC', value.removeprefix('#'))
        if not 1 <= len(value) <= 10 or not all(c.isalnum() or c == '_' for c in value):
            raise ValueError('해시태그는 #을 제외한 한글·영문·숫자·밑줄 1~10자입니다.')
        return value


class AssignmentInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    assigned: bool
    fee_override: int | None = Field(default=None, strict=True, ge=0, le=10**12)


def contract_id(tag):
    return hashlib.sha256(tag.casefold().encode()).hexdigest()[:24]


def require_contract(db, identity):
    if not re.fullmatch(r'[a-f0-9]{24}', identity):
        raise HTTPException(422, '잘못된 협업 ID입니다.')
    row = db.collection('collaborations').document(identity).get(timeout=10)
    if not row.exists:
        raise HTTPException(404, '협업을 찾을 수 없습니다.')
    return row


def fee_summary(contract):
    assignments = contract.get('posts', {})
    agreed = contract['fee'] if contract['fee_mode'] == 'bundle' else sum(
        row['fee_override'] if row.get('fee_override') is not None else contract['fee']
        for row in assignments.values())
    paid = contract.get('paid_amount', 0)
    return {'agreed': agreed, 'paid': paid, 'outstanding': max(0, agreed - paid),
            'overpaid': max(0, paid - agreed),
            'status': '초과 입금' if paid > agreed else '정산 완료' if paid == agreed and agreed > 0 else '일부 입금' if paid else '미입금'}


def analysis_record(identity, contract):
    return {'date':contract['date'], 'value':fee_summary(contract)['agreed'],
            'memo':contract.get('memo',''), 'metric':'collaboration_fee', 'unit':'KRW',
            'source':'collaboration', 'contract_id':identity, 'tag':contract['tag'],
            'fee_mode':contract['fee_mode'], 'fee':contract['fee'],
            'paid_amount':contract.get('paid_amount',0), 'updated_at':contract['updated_at']}


def performance(post_ids, insights, follows):
    totals, coverage = {}, {}
    for key in ('views', 'likes', 'replies', 'reposts', 'follows'):
        rows = follows if key == 'follows' else insights
        values = [rows.get(pid, {}).get(key) for pid in post_ids]
        known = [value for value in values if type(value) is int and value >= 0]
        totals[key] = sum(known) if known else None
        coverage[key] = len(known)
    return {'totals': totals, 'coverage': coverage, 'post_count': len(post_ids)}


@router.get('/catalog')
def catalog(db=Depends(database)):
    rows = list(db.collection('threads_posts').limit(1001).stream(timeout=30))
    if len(rows) > 1000:
        raise HTTPException(503, '게시물 선택 목록이 1,000개를 초과했습니다.')
    posts = [{**row.to_dict(), 'id': row.id} for row in rows]
    posts = [p for p in posts if p.get('media_type', '').upper() != 'REPOST_FACADE']
    posts.sort(key=lambda p: (p['timestamp'], p['id']), reverse=True)
    return {'items': posts}


@router.get('')
def list_contracts(db=Depends(database)):
    rows = list(db.collection('collaborations').limit(301).stream(timeout=30))
    if len(rows) > 300:
        raise HTTPException(503, '협업 목록이 300개를 초과했습니다.')
    contracts = [{**row.to_dict(), 'id': row.id} for row in rows]
    post_ids = set().union(*(set(c.get('posts', {})) for c in contracts)) if contracts else set()
    insights, follows, posts = {}, {}, {}
    if post_ids:
        refs = [db.collection('threads_posts').document(pid) for pid in post_ids]
        for row in db.get_all(refs, timeout=30):
            if not row.exists:
                continue
            posts[row.id] = {**row.to_dict(), 'id': row.id}
            readings = list(row.reference.collection('insights').order_by(
                'collected_at', direction='DESCENDING').limit(1).stream(timeout=10))
            if readings:
                insights[row.id] = readings[0].to_dict()
        for row in db.get_all([db.collection('post_follower_insights').document(pid) for pid in post_ids], timeout=30):
            if row.exists:
                follows[row.id] = row.to_dict()
    for contract in contracts:
        ids = set(contract.get('posts', {}))
        contract['finance'] = fee_summary(contract)
        contract['performance'] = performance(ids, insights, follows)
        contract['items'] = [{**posts.get(pid, {'id': pid, 'text': '(원본을 찾을 수 없는 게시물)'}),
                              'fee_override': assignment.get('fee_override'),
                              'latest_insight': insights.get(pid), 'follower_insight': follows.get(pid)}
                             for pid, assignment in contract.get('posts', {}).items()]
    contracts.sort(key=lambda c: (c['date'], c['id']), reverse=True)
    return {'items': contracts,
            'finance': {key: sum(c['finance'][key] for c in contracts)
                        for key in ('agreed', 'paid', 'outstanding', 'overpaid')},
            'performance': performance(post_ids, insights, follows)}


@router.post('', status_code=201)
def create_contract(body: ContractInput, db=Depends(database)):
    identity = contract_id(body.tag)
    ref = db.collection('collaborations').document(identity)
    @firestore.transactional
    def save(transaction):
        if ref.get(transaction=transaction).exists:
            raise HTTPException(409, '같은 해시태그가 이미 있습니다.')
        now = datetime.now(timezone.utc)
        contract={**body.model_dump(mode='json'), 'posts': {}, 'created_at': now, 'updated_at': now}
        transaction.set(ref, contract)
        transaction.set(db.collection('data').document('collaboration_'+identity),analysis_record(identity,contract))
    save(db.transaction())
    return {'id': identity}


@router.put('/{identity}')
def update_contract(identity: str, body: ContractInput, db=Depends(database)):
    row = require_contract(db, identity)
    if contract_id(body.tag) != identity:
        raise HTTPException(422, '해시태그 이름은 변경할 수 없습니다. 새 협업으로 만들어 주세요.')
    @firestore.transactional
    def save(transaction):
        current=row.reference.get(transaction=transaction)
        if not current.exists:raise HTTPException(404,'협업을 찾을 수 없습니다.')
        contract={**current.to_dict(), **body.model_dump(mode='json'), 'updated_at':datetime.now(timezone.utc)}
        transaction.set(row.reference,contract)
        transaction.set(db.collection('data').document('collaboration_'+identity),analysis_record(identity,contract))
    save(db.transaction())
    return {'id': identity}


@router.put('/{identity}/posts/{post_id}')
def assign_post(identity: str, post_id: PostId, body: AssignmentInput, db=Depends(database)):
    require_post(db, post_id)
    row = require_contract(db, identity)
    @firestore.transactional
    def save(transaction):
        latest = row.reference.get(transaction=transaction)
        if not latest.exists:
            raise HTTPException(404, '협업을 찾을 수 없습니다.')
        data = latest.to_dict()
        assigned = dict(data.get('posts', {}))
        if body.assigned:
            if body.fee_override is not None and data['fee_mode'] != 'per_post':
                raise HTTPException(422, '일괄 원고료는 게시물별 금액을 설정하지 않습니다.')
            assigned[post_id] = {'fee_override': body.fee_override}
        else:
            assigned.pop(post_id, None)
        if len(assigned) > 500:
            raise HTTPException(422, '협업당 최대 500개 게시물을 연결할 수 있습니다.')
        contract={**data,'posts':assigned,'updated_at':datetime.now(timezone.utc)}
        transaction.set(row.reference,contract)
        transaction.set(db.collection('data').document('collaboration_'+identity),analysis_record(identity,contract))
    save(db.transaction())
    return {'post_id': post_id, 'assigned': body.assigned}


@router.delete('/{identity}', status_code=204)
def delete_contract(identity: str, db=Depends(database)):
    row = require_contract(db, identity)
    @firestore.transactional
    def remove(transaction):
        current=row.reference.get(transaction=transaction)
        if not current.exists:raise HTTPException(404,'협업을 찾을 수 없습니다.')
        transaction.delete(row.reference)
        transaction.delete(db.collection('data').document('collaboration_'+identity))
    remove(db.transaction())
