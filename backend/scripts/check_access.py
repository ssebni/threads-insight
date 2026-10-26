"""Offline access-control tests; no cloud services or credentials used."""
import asyncio
import os
from unittest.mock import patch
from starlette.responses import JSONResponse
from app.access import AccessMiddleware

async def main():
    called=0
    async def endpoint(scope,receive,send):
        nonlocal called
        called+=1
        await JSONResponse({'ok':True})(scope,receive,send)
    middleware=AccessMiddleware(endpoint)
    async def call(path='/api/dashboard',token='',method='GET'):
        messages=[]
        async def receive():return {'type':'http.request','body':b''}
        async def send(message):messages.append(message)
        await middleware({'type':'http','path':path,'method':method,'headers':[(b'authorization',token.encode())]},receive,send)
        return messages[0]['status']
    with patch.dict(os.environ,{'RENDER':'true','APP_ACCESS_TOKEN':'test-access'}):
        assert await call()==401 and called==0
        assert await call(token='Bearer 틀린키')==401 and called==0
        assert await call(token='Bearer test-access')==200 and called==1
        assert await call('/health')==200
        assert await call('/docs')==200
        assert await call(method='OPTIONS')==200
    with patch.dict(os.environ,{'RENDER':'true','APP_ACCESS_TOKEN':''}):assert await call()==503
    with patch.dict(os.environ,{'RENDER':'','APP_ACCESS_TOKEN':''}):assert await call()==200
    print('PASS: deployed API authentication, health/docs, CORS preflight, local preview')

if __name__=='__main__':asyncio.run(main())
