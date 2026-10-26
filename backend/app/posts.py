from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from google.cloud.firestore_v1 import Query as FirestoreQuery
from pydantic import BaseModel

from app.database import get_database

router = APIRouter(prefix='/api/v1/posts', tags=['posts'])
PostId = Annotated[str, Path(pattern=r'^[0-9]{1,64}$')]
PageSize = Annotated[int, Query(ge=1, le=100)]
Cursor = Annotated[str | None, Query(pattern=r'^[0-9]{1,64}$')]


class Insight(BaseModel):
    post_id: str
    timestamp: datetime
    collected_at: datetime
    status: Literal['success', 'empty']
    views: int | None
    likes: int | None
    replies: int | None
    reposts: int | None
    quotes: int | None


class Post(BaseModel):
    id: str
    text: str
    timestamp: datetime
    media_type: str
    permalink: str
    latest_insight: Insight | None = None


class PostPage(BaseModel):
    items: list[Post]
    next_cursor: str | None
    has_more: bool


def database():
    try:
        return get_database()
    except (RuntimeError, ValueError, OSError):
        raise HTTPException(503, 'Database is unavailable') from None


def require_post(db, post_id):
    snapshot = db.collection('threads_posts').document(post_id).get(timeout=10)
    if not snapshot.exists:
        raise HTTPException(404, 'Post not found')
    return snapshot


def serialize_post(snapshot):
    latest = list(snapshot.reference.collection('insights').order_by(
        'collected_at', direction=FirestoreQuery.DESCENDING
    ).limit(1).stream(timeout=10))
    return Post(**{**snapshot.to_dict(), 'id': snapshot.id,
                   'latest_insight': latest[0].to_dict() if latest else None})


@router.get('', response_model=PostPage)
def list_posts(limit: PageSize = 20, cursor: Cursor = None, db=Depends(database)):
    """Newest posts first. Pass next_cursor as cursor to fetch the next page."""
    query = db.collection('threads_posts').order_by(
        'timestamp', direction=FirestoreQuery.DESCENDING
    )
    if cursor:
        anchor = db.collection('threads_posts').document(cursor).get(timeout=10)
        if not anchor.exists:
            raise HTTPException(400, 'Cursor post no longer exists')
        query = query.start_after(anchor)
    snapshots = list(query.limit(limit + 1).stream(timeout=10))
    has_more = len(snapshots) > limit
    page = snapshots[:limit]
    return PostPage(items=[serialize_post(s) for s in page], has_more=has_more,
                    next_cursor=page[-1].id if has_more else None)


@router.get('/{post_id}', response_model=Post)
def get_post(post_id: PostId, db=Depends(database)):
    return serialize_post(require_post(db, post_id))


class InsightPage(BaseModel):
    items: list[Insight]
    has_more: bool
    next_cursor: str | None


@router.get('/{post_id}/insights', response_model=InsightPage)
def list_insights(
    post_id: PostId, limit: PageSize = 20,
    cursor: Annotated[str | None, Query(pattern=r'^[a-f0-9]{24}$')] = None,
    db=Depends(database),
):
    """Collection history, newest first. Missing metrics remain null."""
    post = require_post(db, post_id)
    collection = post.reference.collection('insights')
    query = collection.order_by('collected_at', direction=FirestoreQuery.DESCENDING)
    if cursor:
        anchor = collection.document(cursor).get(timeout=10)
        if not anchor.exists:
            raise HTTPException(400, 'Cursor insight no longer exists')
        query = query.start_after(anchor)
    snapshots = list(query.limit(limit + 1).stream(timeout=10))
    page = snapshots[:limit]
    has_more = len(snapshots) > limit
    return InsightPage(items=[Insight(**s.to_dict()) for s in page],
                       has_more=has_more, next_cursor=page[-1].id if has_more else None)
