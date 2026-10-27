import json
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.posts import database
from app.chat_memory import clear_answer_memory, question_key

router = APIRouter(prefix='/api/conversations', tags=['conversations'])


class Message(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    role: Literal['user', 'assistant']
    content: str = Field(min_length=1, max_length=8000)


class ConversationInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=120)
    messages: list[Message] = Field(min_length=1, max_length=60)

    @model_validator(mode='after')
    def check_size(self):
        if len(json.dumps(self.model_dump(), ensure_ascii=False).encode()) > 250000:
            raise ValueError('Conversation is too large')
        return self


def require_conversation(db, conversation_id):
    if not conversation_id.isascii() or not conversation_id.isalnum() or len(conversation_id) > 64:
        raise HTTPException(422, 'Invalid conversation ID')
    snapshot = db.collection('conversations').document(conversation_id).get(timeout=10)
    if not snapshot.exists:
        raise HTTPException(404, 'Conversation not found')
    return snapshot


@router.post('', status_code=201)
def save_conversation(body: ConversationInput, db=Depends(database)):
    now = datetime.now(timezone.utc)
    ref = db.collection('conversations').document()
    payload = {**body.model_dump(), 'created_at': now, 'updated_at': now}
    ref.create(payload, timeout=10)
    clear_answer_memory()
    return {**payload, 'id': ref.id}


@router.get('')
def list_conversations(limit: int = Query(30, ge=1, le=100),
                       cursor: str | None = Query(None, max_length=64, pattern=r'^[A-Za-z0-9]+$'),
                       db=Depends(database)):
    # List intentionally omits messages; GET /{id} loads the complete conversation.
    query = db.collection('conversations').order_by('updated_at', direction='DESCENDING')
    if cursor:
        anchor = require_conversation(db, cursor)
        query = query.start_after(anchor)
    rows = list(query.limit(limit + 1).stream(timeout=15))
    def entry(snapshot):
        row = snapshot.to_dict()
        first = next((message['content'] for message in row.get('messages',[]) if message.get('role')=='user'), None)
        return {**{k:v for k,v in row.items() if k!='messages'}, 'id':snapshot.id,
                'question_key':question_key(first) if first else snapshot.id}
    return {'items': [entry(snapshot) for snapshot in rows[:limit]],
            'has_more': len(rows) > limit,
            'next_cursor': rows[limit - 1].id if len(rows) > limit else None}


@router.get('/{conversation_id}')
def get_conversation(conversation_id: str, db=Depends(database)):
    snapshot = require_conversation(db, conversation_id)
    return {**snapshot.to_dict(), 'id': snapshot.id}


@router.delete('/{conversation_id}', status_code=204)
def delete_conversation(conversation_id: str, db=Depends(database)):
    require_conversation(db, conversation_id).reference.delete(timeout=10)
    clear_answer_memory()
