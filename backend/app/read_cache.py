"""Single-account local read cache. Firestore remains the authoritative database."""
import asyncio
import json
import os
import threading
import time
from pathlib import Path

from starlette.responses import JSONResponse

FILE = Path(__file__).resolve().parents[1] / 'work' / 'read-cache.json'
TTL = 300
MAX_BYTES = 8 * 1024 * 1024
_mutex = threading.RLock()
_entries = {}
_quota_until = 0
_generation = 0
_loaded = False
PREFIXES = ('/api/dashboard', '/api/data', '/api/v1/posts', '/api/memos', '/api/collaborations', '/api/conversations')


def load():
    global _loaded
    with _mutex:
        if _loaded:
            return
        _loaded = True
        try:
            if FILE.stat().st_size <= MAX_BYTES:
                rows = json.loads(FILE.read_text(encoding='utf-8'))
                for key, row in rows.items():
                    if isinstance(row, dict) and isinstance(row.get('body'), str) and isinstance(row.get('at'), (int, float)):
                        _entries[key] = row
        except (OSError, ValueError, AttributeError):
            pass


def persist():
    try:
        while len(_entries) > 128 or len(json.dumps(_entries, ensure_ascii=False).encode()) > MAX_BYTES:
            _entries.pop(min(_entries, key=lambda key:_entries[key]['at']))
        FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = FILE.with_suffix('.tmp')
        temporary.write_text(json.dumps(_entries,ensure_ascii=False),encoding='utf-8')
        os.replace(temporary,FILE)
    except OSError:
        pass


def invalidate(prefixes=PREFIXES, retain=False):
    global _generation
    load()
    with _mutex:
        _generation += 1
        for key in list(_entries):
            if any(key.split('?')[0] == prefix or key.startswith(prefix+'/') for prefix in prefixes):
                if retain:
                    _entries[key]['expired'] = True
                else:
                    del _entries[key]
        persist()


def remember_quota():
    global _quota_until
    _quota_until = time.time() + TTL


class ReadCacheMiddleware:
    def __init__(self, app):
        self.app=app
        self.locks={}

    async def __call__(self,scope,receive,send):
        if scope['type'] != 'http':
            return await self.app(scope,receive,send)
        path=scope['path'];method=scope['method']
        if method=='POST' and path in ('/api/chat','/api/v1/sync/run') and time.time()<_quota_until:
            response=JSONResponse({'detail':'Firestore 한도 초과로 새 조회·대화 저장이 일시 중단됐습니다. 한도가 복구된 뒤 다시 시도해 주세요.'},status_code=503)
            return await response(scope,receive,send)
        cacheable=any(path==prefix or path.startswith(prefix+'/') for prefix in PREFIXES)
        if method != 'GET' or not cacheable or len(scope.get('query_string',b''))>512:
            async def forward(message):
                if message['type']=='http.response.start' and message['status']<400 and method in ('POST','PUT','DELETE'):
                    groups=tuple(prefix for prefix in PREFIXES if path==prefix or path.startswith(prefix+'/'))
                    if path.startswith('/api/data') or path.startswith('/api/collaborations'):
                        groups=tuple(set(groups+('/api/data','/api/collaborations')))
                    if groups:invalidate(groups)
                    if path=='/api/chat':invalidate(('/api/conversations',))
                await send(message)
            return await self.app(scope,receive,forward)
        load()
        key=path+'?'+scope.get('query_string',b'').decode('ascii',errors='replace')
        lock=self.locks.setdefault(key,asyncio.Lock())
        async with lock:
            now=time.time()
            with _mutex:
                row=_entries.get(key)
                version=_generation
            if row and not row.get('expired') and now-row['at']<TTL:
                return await self.cached(row,False,scope,receive,send)
            if now < _quota_until:
                if row:return await self.cached(row,True,scope,receive,send)
                response=JSONResponse({'detail':'Firestore 읽기 한도 초과로 잠시 DB 조회를 쉬고 있습니다. 이 화면은 아직 저장된 캐시가 없어 표시할 수 없습니다. 한도 복구 후 다시 시도해 주세요.'},status_code=503,headers={'Retry-After':str(max(1,int(_quota_until-now)))})
                return await response(scope,receive,send)
            messages=[]
            async def capture(message):messages.append(message)
            await self.app(scope,receive,capture)
            start=next(message for message in messages if message['type']=='http.response.start')
            body=b''.join(message.get('body',b'') for message in messages if message['type']=='http.response.body')
            if start['status']==503 and 'Firestore 사용량 한도를 초과'.encode() in body:
                remember_quota()
                if row:return await self.cached(row,True,scope,receive,send)
            if start['status']==200 and len(body)<2*1024*1024:
                try:
                    text=body.decode('utf-8');json.loads(text)
                    with _mutex:
                        if version==_generation:
                            _entries[key]={'body':text,'at':time.time()}
                            persist()
                except (UnicodeError,ValueError):pass
            for message in messages:await send(message)

    async def cached(self,row,stale,scope,receive,send):
        response=JSONResponse(json.loads(row['body']),headers={
            'X-Data-Cache':'stale' if stale else 'hit',
            'X-Data-Cached-At':str(row['at']),
            'Cache-Control':'no-store',
        })
        await response(scope,receive,send)
