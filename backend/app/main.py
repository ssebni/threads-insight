import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.openapi.utils import get_openapi
from google.api_core.exceptions import GoogleAPICallError, ResourceExhausted
from google.auth.exceptions import GoogleAuthError

from app.posts import router
from app.threads_sync import lifespan, router as sync_router
from app.data_api import router as data_router
from app.conversations import router as conversations_router
from app.chat import router as chat_router
from app.dashboard import router as dashboard_router
from app.memos import router as memos_router
from app.collaborations import router as collaborations_router
from app.read_cache import ReadCacheMiddleware, remember_quota
from app.access import AccessMiddleware

app = FastAPI(title='Threads Insight API', version='0.3.0', lifespan=lifespan)
app.add_middleware(ReadCacheMiddleware)
app.add_middleware(AccessMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[s.strip() for s in os.getenv('ALLOWED_ORIGINS', 'http://localhost:5500,http://127.0.0.1:5500').split(',') if s.strip()],
    allow_methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
    allow_headers=['Content-Type','Authorization'],
    expose_headers=['X-Data-Cache', 'X-Data-Cached-At'],
)
app.include_router(router)
app.include_router(sync_router)
app.include_router(data_router)
app.include_router(conversations_router)
app.include_router(chat_router)
app.include_router(dashboard_router)
app.include_router(memos_router)
app.include_router(collaborations_router)


def openapi_schema():
    if app.openapi_schema:return app.openapi_schema
    schema=get_openapi(title=app.title,version=app.version,routes=app.routes)
    schema.setdefault('components',{}).setdefault('securitySchemes',{})['SiteAccess']={'type':'http','scheme':'bearer','description':'배포 사이트 접근키. 로컬은 설정하지 않으면 불필요합니다.'}
    for path,methods in schema['paths'].items():
        if path.startswith('/api/'):
            for method,operation in methods.items():
                if method in ('get','post','put','delete'):operation['security']=[{'SiteAccess':[]}]
    app.openapi_schema=schema
    return schema


app.openapi=openapi_schema


async def database_error(request, exc):
    if isinstance(exc, ResourceExhausted):
        remember_quota()
        return JSONResponse(status_code=503, content={'detail': 'Firestore 사용량 한도를 초과했습니다. Firebase 콘솔에서 할당량과 결제 설정을 확인해 주세요. 마지막 표시값은 유지됩니다.'})
    return JSONResponse(status_code=503, content={'detail': 'Database is unavailable'})


app.add_exception_handler(GoogleAPICallError, database_error)
app.add_exception_handler(GoogleAuthError, database_error)


@app.get('/health', tags=['health'])
def health():
    return {'status': 'ok', 'service': 'threads-insight-api'}


@app.get('/', include_in_schema=False)
def home():
    return RedirectResponse('/dashboard/')


frontend = Path(__file__).resolve().parents[2] / 'frontend'
if frontend.is_dir():
    app.mount('/dashboard', StaticFiles(directory=frontend, html=True), name='dashboard')
