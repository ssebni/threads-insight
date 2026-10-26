from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from google.cloud.firestore_v1.base_query import FieldFilter

from app.posts import database
from app.collaborations import ContractInput, create_contract, update_contract, delete_contract

router = APIRouter(prefix='/api/data', tags=['data'])


class CollaborationFields(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tag: str
    fee_mode: Literal['bundle','per_post'] = 'bundle'
    paid_amount: int = Field(default=0,strict=True,ge=0,le=10**12)


class DataInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    date: date
    value: float = Field(ge=0, le=1e12, allow_inf_nan=False)
    memo: str = Field(default='', max_length=2000)
    collaboration: CollaborationFields | None = None

    @model_validator(mode='after')
    def validate_contract(self):
        if self.collaboration:
            if not self.value.is_integer():raise ValueError('원고료는 원 단위 정수로 입력해 주세요.')
            self.contract()
        return self

    def contract(self):
        return ContractInput(**self.collaboration.model_dump(),date=self.date,fee=int(self.value),memo=self.memo)


def output(snapshot):
    return {**snapshot.to_dict(), 'id': snapshot.id}


def require_data(db, record_id):
    if not record_id or '/' in record_id or len(record_id) > 128:
        raise HTTPException(422, 'Invalid record ID')
    snapshot = db.collection('data').document(record_id).get(timeout=10)
    if not snapshot.exists:
        raise HTTPException(404, 'Data not found')
    return snapshot


def summary_for(db):
    snapshots = list(db.collection('data').limit(10001).stream(timeout=30))
    if len(snapshots) > 10000:
        raise HTTPException(503, 'Summary capacity exceeded')
    all_rows = [s.to_dict() for s in snapshots]
    rows = [row for row in all_rows if row.get('metric','views')=='views']
    fees = [row for row in all_rows if row.get('metric')=='collaboration_fee']
    values = [r['value'] for r in rows]
    daily = defaultdict(float)
    for row in rows:
        daily[row['date']] += row['value']
    dates = sorted(daily)
    trend = {'label': '데이터 부족', 'change_percent': None,
             'method': '최근 7일과 직전 7일의 게시일별 조회수 합계 비교. 누락 날짜는 0.'}
    if dates:
        end = date.fromisoformat(dates[-1])
        recent = sum(daily.get((end - timedelta(days=i)).isoformat(), 0) for i in range(7))
        previous = sum(daily.get((end - timedelta(days=i)).isoformat(), 0) for i in range(7, 14))
        if date.fromisoformat(dates[0]) <= end - timedelta(days=7) and previous > 0:
            change = (recent - previous) / previous * 100
            trend.update(label='증가' if change > 1 else '감소' if change < -1 else '유지',
                         change_percent=round(change, 2))
    return {
        'period': {'start': dates[0] if dates else None, 'end': dates[-1] if dates else None},
        'count': len(rows), 'target_count': 100, 'meets_minimum': len(rows) >= 100,
        'collaboration_revenue': {'count':len(fees),'unit':'KRW',
                                  'agreed_total':sum(row['value'] for row in fees),
                                  'paid_total':sum(row.get('paid_amount',0) for row in fees)},
        'metric': '조회수', 'unit': '회',
        'metrics': {'total': sum(values), 'average': sum(values) / len(values) if values else None,
                    'max': max(values) if values else None, 'min': min(values) if values else None},
        'trend': trend,
        'daily': [{'date': d, 'value': daily[d]} for d in dates],
        'sources': {'threads': sum(r.get('source') == 'threads' for r in rows),
                    'manual': sum(r.get('source') == 'manual' for r in rows)},
        'note': 'Threads 항목은 게시물별 최신 누적 조회수 1건입니다. 반복 수집 횟수를 데이터 개수로 세지 않습니다. 게시일별 추세는 계정의 일별 신규 조회수가 아닙니다.',
    }


@router.get('/summary')
def summary(db=Depends(database)):
    return summary_for(db)


@router.get('')
def list_data(limit: Annotated[int, Query(ge=1, le=100)] = 30,
              cursor: Annotated[str | None, Query(max_length=128, pattern=r'^[A-Za-z0-9_-]+$')] = None,
              kind: Literal['collaboration'] | None = None,
              db=Depends(database)):
    if kind=='collaboration':
        rows=list(db.collection('data').where(filter=FieldFilter('metric','==','collaboration_fee')).limit(1001).stream(timeout=15))
        if len(rows)>1000:raise HTTPException(503,'협업 분석 데이터가 너무 많습니다.')
        rows.sort(key=lambda row:(row.to_dict()['date'],row.id),reverse=True)
        if cursor:
            position=next((i for i,row in enumerate(rows) if row.id==cursor),None)
            if position is None:raise HTTPException(400,'데이터 목록이 변경됐습니다.')
            rows=rows[position+1:]
        page=rows[:limit]
        return {'items':[output(row) for row in page], 'has_more':len(rows)>limit,
                'next_cursor':page[-1].id if len(rows)>limit else None}
    query = db.collection('data').order_by('date', direction='DESCENDING')
    if cursor:
        anchor = db.collection('data').document(cursor).get(timeout=10)
        if not anchor.exists:
            raise HTTPException(400, 'Cursor not found')
        query = query.start_after(anchor)
    rows = list(query.limit(limit + 1).stream(timeout=15))
    page = rows[:limit]
    return {'items': [output(s) for s in page], 'has_more': len(rows) > limit,
            'next_cursor': page[-1].id if len(rows) > limit else None}


@router.post('', status_code=201)
def create_data(body: DataInput, db=Depends(database)):
    if body.collaboration:
        result=create_contract(body.contract(),db)
        row=db.collection('data').document('collaboration_'+result['id']).get(timeout=10)
        return output(row)
    now = datetime.now(timezone.utc)
    ref = db.collection('data').document()
    payload = {**body.model_dump(mode='json',exclude={'collaboration'}), 'source': 'manual', 'metric': 'views',
               'created_at': now, 'updated_at': now}
    ref.create(payload, timeout=10)
    return {**payload, 'id': ref.id}


@router.put('/{record_id}')
def update_data(record_id: str, body: DataInput, db=Depends(database)):
    if record_id.startswith('collaboration_'):
        if not body.collaboration:raise HTTPException(422,'협업 원고료 정보를 함께 입력해 주세요.')
        result=update_contract(record_id.removeprefix('collaboration_'),body.contract(),db)
        return output(db.collection('data').document(record_id).get(timeout=10))
    if body.collaboration:raise HTTPException(422,'조회수 데이터는 협업 데이터로 변경할 수 없습니다.')
    snapshot = require_data(db, record_id)
    if snapshot.to_dict().get('source') == 'threads':
        raise HTTPException(409, '자동 수집 데이터는 원본 보호를 위해 수정할 수 없습니다. 수동 데이터를 추가해 주세요.')
    payload = {**body.model_dump(mode='json',exclude={'collaboration'}), 'updated_at': datetime.now(timezone.utc)}
    snapshot.reference.update(payload, timeout=10)
    return {**snapshot.to_dict(), **payload, 'id': record_id}


@router.delete('/{record_id}', status_code=204)
def delete_data(record_id: str, db=Depends(database)):
    if record_id.startswith('collaboration_'):
        return delete_contract(record_id.removeprefix('collaboration_'),db)
    snapshot = require_data(db, record_id)
    if snapshot.to_dict().get('source') == 'threads':
        raise HTTPException(409, '자동 수집 데이터는 원본 보호를 위해 삭제할 수 없습니다.')
    snapshot.reference.delete(timeout=10)
