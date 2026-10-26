"""Protect the personal API on Render; public health/docs remain available."""
import hmac
import os
from starlette.responses import JSONResponse


class AccessMiddleware:
    def __init__(self, app):self.app=app
    async def __call__(self,scope,receive,send):
        path=scope.get('path','')
        if scope['type']=='http' and path.startswith('/api/') and scope['method']!='OPTIONS':
            expected=os.getenv('APP_ACCESS_TOKEN','').strip()
            required=bool(expected) or os.getenv('RENDER','').lower()=='true'
            if required:
                headers=dict(scope.get('headers',[]))
                supplied=headers.get(b'authorization',b'').decode('utf-8',errors='replace')
                if not expected:
                    response=JSONResponse({'detail':'배포 서버 접근키 설정이 필요합니다.'},status_code=503)
                    return await response(scope,receive,send)
                if not hmac.compare_digest(supplied.encode(),('Bearer '+expected).encode()):
                    response=JSONResponse({'detail':'사이트 접근키를 입력해 주세요.'},status_code=401)
                    return await response(scope,receive,send)
        await self.app(scope,receive,send)
