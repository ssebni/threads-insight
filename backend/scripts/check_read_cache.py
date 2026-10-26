"""Offline ASGI cache checks. No Firestore, model calls, or production snapshots."""
import asyncio
import json
import tempfile
import time
from pathlib import Path
from unittest.mock import patch
from starlette.responses import JSONResponse
from app import read_cache as cache


async def main():
    count=0
    quota=False
    async def downstream(scope,receive,send):
        nonlocal count
        count+=1
        response=JSONResponse({'detail':'Firestore 사용량 한도를 초과했습니다.'},status_code=503) if quota else JSONResponse({'value':count})
        await response(scope,receive,send)
    app=cache.ReadCacheMiddleware(downstream)
    async def call(path='/api/dashboard',method='GET'):
        messages=[]
        async def receive():return {'type':'http.request','body':b'','more_body':False}
        async def send(message):messages.append(message)
        await app({'type':'http','method':method,'path':path,'query_string':b'','headers':[]},receive,send)
        status=messages[0]['status'];headers=dict(messages[0].get('headers',[]))
        body=json.loads(b''.join(m.get('body',b'') for m in messages))
        return status,headers,body
    a,b=await asyncio.gather(call(),call())
    assert count==1 and a[2]==b[2]
    assert b[1][b'x-data-cache']==b'hit'
    assert cache.FILE.exists()
    cache._entries.clear();cache._loaded=False
    assert (await call())[2]==a[2] and count==1  # Survives a server restart.
    await call('/api/memos')
    await call('/api/memos/123','PUT')
    await call('/api/memos')
    assert count==4
    await call()
    assert count==4  # Memo changes do not flush dashboard.
    cache.invalidate(retain=True);quota=True
    stale=await call()
    assert stale[0]==200 and stale[1][b'x-data-cache']==b'stale' and count==5
    await call()
    assert count==5  # Repeated quota errors don't hit Firestore again.
    assert (await call('/api/collaborations'))[0]==503 and count==5  # Never invent a missing snapshot.
    assert (await call('/api/chat','POST'))[0]==503 and count==5  # No paid model call without persistence.
    cache._quota_until=0;quota=False
    assert (await call())[2]!=a[2] and count==6
    await call('/api/v1/sync/status');await call('/api/v1/sync/status')
    assert count==8  # Live progress is never cached.
    print('PASS: concurrent deduplication, restart persistence, CRUD invalidation, stale flag, quota cooldown and recovery')


if __name__=='__main__':
    with tempfile.TemporaryDirectory() as folder, patch.object(cache,'FILE',Path(folder)/'cache.json'):
        cache._entries.clear();cache._loaded=False;cache._quota_until=0
        asyncio.run(main())
