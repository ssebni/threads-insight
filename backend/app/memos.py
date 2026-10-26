from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.posts import PostId, database, require_post

router = APIRouter(prefix='/api/memos', tags=['memos'])


class MemoInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    memo: str = Field(min_length=1, max_length=10000)


@router.get('')
def list_memos(limit: Annotated[int, Query(ge=1, le=100)] = 20,
               cursor: Annotated[str | None, Query(pattern=r'^[0-9]{1,64}$')] = None,
               db=Depends(database)):
    query = db.collection('post_memos').order_by('updated_at', direction='DESCENDING')
    if cursor:
        anchor = db.collection('post_memos').document(cursor).get(timeout=10)
        if not anchor.exists:
            raise HTTPException(400, '메모 목록이 변경됐습니다. 새로고침해 주세요.')
        query = query.start_after(anchor)
    rows = list(query.limit(limit + 1).stream(timeout=15))
    return {'items': [{**s.to_dict(), 'post_id': s.id} for s in rows[:limit]],
            'has_more': len(rows) > limit,
            'next_cursor': rows[limit - 1].id if len(rows) > limit else None}


@router.get('/{post_id}')
def get_memo(post_id: PostId, db=Depends(database)):
    require_post(db, post_id)
    snapshot = db.collection('post_memos').document(post_id).get(timeout=10)
    return {**(snapshot.to_dict() or {}), 'post_id': post_id,
            'memo': snapshot.to_dict()['memo'] if snapshot.exists else ''}


@router.put('/{post_id}')
def save_memo(post_id: PostId, body: MemoInput, db=Depends(database)):
    post = require_post(db, post_id).to_dict()
    payload = {'post_id': post_id, 'memo': body.memo,
               'post_text': post.get('text', ''), 'post_timestamp': post['timestamp'],
               'permalink': post.get('permalink', ''),
               'updated_at': datetime.now(timezone.utc)}
    db.collection('post_memos').document(post_id).set(payload, timeout=10)
    return payload


@router.delete('/{post_id}', status_code=204)
def delete_memo(post_id: PostId, db=Depends(database)):
    db.collection('post_memos').document(post_id).delete(timeout=10)
