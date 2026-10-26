# Threads Insight

Threads 게시물 성과, 협업 원고료, 메모와 데이터 기반 AI 채팅을 제공하는 개인 작업실입니다.

## 기술 스택

FastAPI · Pydantic · Firebase Firestore · 바닐라 HTML/CSS/JavaScript · 코디세이 Anthropic Messages API (Claude). 백엔드 Render, 프런트 Vercel을 사용합니다. 현재 Claude를 사용하며 과제의 GPT 대체 인정 여부는 사용자 확인 사항입니다.

## 주요 기능

- 게시물 조회·좋아요·댓글·리포스트, 팔로워 순증 그래프, Best Threads.
- 협업 해시태그(최대 10자), 게시물 연결, 지표 합산과 확인 범위 표시.
- 협업 전체 일괄/게시물별 원고료, 개별 단가, 입금액·미수금·초과 입금 관리.
- 게시물별 자유 텍스트 메모, 저장·수정·삭제.
- AI에 저장 데이터 요약과 질문 관련 게시물 본문·지표를 전달하고 대화를 자동 저장·불러오기.
- 자동 반복 수집 중단, 수동 갱신, 5분 GET 캐시와 Firestore 한도 초과 안내.

## 데이터 관리와 분석

협업 관리 화면은 지정 `POST/GET /api/data`, `PUT/DELETE /api/data/{id}`와 연결됩니다. `date`는 협업 기준일, `value`는 전체 약정 원고료(원), `memo`는 협업 메모입니다. 게시물별 원고료의 입력 단가와 연결 게시물은 추가 필드로 관리하고 총액을 분석 기록에 반영합니다. `data/collaboration_{id}`와 `collaborations/{id}`를 같은 트랜잭션으로 저장합니다. 기존 협업은 한 번 수정·저장하면 분석 기록이 생성됩니다.

자동 수집한 게시물 조회수는 `data/threads_{id}`에 게시물당 최신값 1건으로 저장하며 원본 수정·삭제를 막습니다. 원고료와 조회수는 지표·단위를 분리하고 합계에 섞지 않습니다. `/api/data/summary`는 조회수 기간·개수·합계·평균·최대·최소·추세와 별도 원고료 요약을 반환합니다. 마지막 실제 확인은 조회수 분석 기록 113개입니다. 반복 수집 횟수는 데이터 개수로 세지 않습니다.

## 로컬 실행

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# .env.example을 참고해 .env를 직접 설정합니다. 기존 .env는 덮어쓰지 않습니다.
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8010
```

대시보드 http://127.0.0.1:8010/dashboard/ · Swagger http://127.0.0.1:8010/docs

## 환경 변수

| 변수 | 용도 |
|---|---|
| GOOGLE_APPLICATION_CREDENTIALS | Firestore 서비스 계정 JSON 경로 |
| FIRESTORE_DATABASE_ID | 기본 `(default)` |
| CODESEI_API_KEY | 코디세이 발급 키, 백엔드 전용 |
| CODESEI_BASE_URL | `https://copa.codyssey.kr` |
| CODESEI_MODEL | `claude-sonnet-4` |
| AI_PROVIDER | `codyssey_anthropic` 또는 기존 `openai` |
| OPENAI_API_KEY / OPENAI_MODEL | OpenAI 공급자 선택 시에만 사용 |
| THREADS_ACCESS_TOKEN | Threads 공식 API 토큰, 백엔드 전용 |
| THREADS_AUTO_SYNC | `false`, 반복 수집 중단 |
| THREADS_ACCOUNT_CREATED_DATE | `2026-10-03` |
| APP_ACCESS_TOKEN | Render 개인 API 보호용 사이트 접근키 |
| ALLOWED_ORIGINS | 실제 Vercel HTTPS 출처 |
| API_BASE_URL | Vercel 공개 빌드 변수, 실제 Render HTTPS 주소 |

키·서비스 계정·DB 캐시는 Git에서 제외합니다. 프런트 빌드에는 API 주소만 들어갑니다. Render에서는 API 접근키를 요구하고 화면에서 입력한 키는 탭 세션에만 보관합니다. Swagger의 Authorize에도 같은 키를 넣을 수 있습니다. 무료 서버 첫 요청 지연·AI 로딩·오류·입력 검증을 처리합니다.

## API

- 데이터: POST/GET `/api/data`, PUT/DELETE `/api/data/{id}`, GET `/api/data/summary`.
- 협업 분석 데이터 목록: GET `/api/data?kind=collaboration`.
- 대화: POST/GET `/api/conversations`, GET/DELETE `/api/conversations/{id}`.
- AI: POST `/api/chat`, GET `/api/chat/status`.
- 대시보드: GET `/api/dashboard`, 게시물: GET `/api/v1/posts` 및 `/{id}`.
- 협업 성과·게시물 연결: `/api/collaborations`.
- 수동 갱신: POST `/api/v1/sync/run`, GET `/api/v1/sync/status`.
- 운영: GET `/health`, Swagger `/docs`.

## 배포

절차와 환경 변수 등록은 [DEPLOYMENT.md](DEPLOYMENT.md)를 참고합니다. 백엔드 root `backend`, 프런트 root `frontend`, Vercel build `node build.mjs`, output `dist`입니다. Render는 단일 worker로 실행합니다.

- 프런트: https://threads-insight-frontend.vercel.app/
- 백엔드: https://threads-insight.onrender.com
- Swagger: https://threads-insight.onrender.com/docs
- GitHub: https://github.com/ssebni/threads-insight (비공개, 평가자 접근 권한은 별도 제공)

2026-10-26 Render Free / Vercel Hobby 배포 성공을 확인했습니다. health·Swagger·정적 프런트 200, 접근키 없는 API 401, 키 있는 AI 상태 조회 200, Vercel 출처의 CORS 사전 요청 200을 검증했습니다. Firestore 읽기 할당량 초과로 실제 데이터 조회와 AI·CRUD 최종 재검증은 미완료입니다. 배포 성공과 기능 최종 검증 완료는 구분합니다.

사이트 접근키는 로컬 `backend/work/deploy-access.env`에 비공개 보관하며 GitHub에 올리지 않습니다. 평가자에게는 별도로 전달합니다. 브라우저 프로필 수집 확장은 로컬 전용이므로 배포 사이트에서 자동 작동하지 않습니다. 저장된 프로필 마지막 값과 공식 API 수집값은 구분합니다.

## 검증과 제출 자료

- 실제 코디세이 Claude 데이터 요약 응답·대화 저장·불러오기 확인 완료.
- 협업 CRUD·합산은 실제 임시 기록으로 검증 후 해당 기록만 정리했습니다.
- 지정 데이터 API와 협업 연결, 단위 분리, 접근키 보호는 오프라인 테스트 통과.
- 개별 게시물 AI 분석 변경 및 지정 데이터 연결의 실제 재검증은 Firestore 읽기 한도 복구 후 필요합니다.
- 제출 캡처: 데이터 요약+질문·답변, 지정 데이터 CRUD 저장 결과, 이전 대화 불러오기. 최종 배포에서 다시 촬영합니다.

backend에서 `python -m scripts.check_data_collaborations`, `scripts.check_collaborations`, `scripts.check_codyssey_chat`, `scripts.check_chat_posts`, `scripts.check_read_cache`, `scripts.check_access`로 오프라인 검증합니다. `check_read_cache`, `check_access`는 Windows 내부 루프백 소켓 사용이 필요할 수 있습니다. `check_required_api`, `check_collaborations_live`는 실제 Firestore 임시 기록을 만들고 정리하므로 한도 복구 후 실행합니다.
