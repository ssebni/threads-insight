# Render / Vercel 배포

## 백엔드 (Render)

- GitHub 비공개 저장소의 main 브랜치, Root Directory `backend`.
- Runtime Python, Build `pip install -r requirements.txt`.
- Start `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1`.
- Health `/health`. 요금제는 Free를 선택합니다. 유료 플랜이나 결제 정보가 필요하면 배포를 멈추고 확인합니다.
- Secret File `firebase-service-account.json`에 사용자 서비스 계정 JSON을 등록합니다. GitHub에는 올리지 않습니다.
- 환경 변수: `GOOGLE_APPLICATION_CREDENTIALS=/etc/secrets/firebase-service-account.json`, `FIRESTORE_DATABASE_ID=(default)`, `AI_PROVIDER=codyssey_anthropic`, `CODESEI_BASE_URL=https://copa.codyssey.kr`, `CODESEI_MODEL=claude-sonnet-4`, `CODESEI_API_KEY`(사용자 키), `APP_ACCESS_TOKEN`(사이트 전용 접근키), `ALLOWED_ORIGINS`(실제 Vercel HTTPS 출처), `THREADS_ACCESS_TOKEN`, `THREADS_AUTO_SYNC=false`, `THREADS_ACCOUNT_CREATED_DATE=2026-10-03`.
- `/docs`는 공개 API 문서이며 **Authorize**에 사이트 접근키를 입력하면 API를 시험할 수 있습니다. 실제 데이터·AI API는 접근키로 보호합니다.

## 프런트엔드 (Vercel)

- 같은 저장소의 Root Directory `frontend`, Framework Other.
- Build `node build.mjs`, Output `dist`.
- 공개 환경 변수는 `API_BASE_URL=https://실제-Render-서비스.onrender.com`만 설정합니다. 비밀 키는 절대 Vercel 프런트 빌드 변수에 넣지 않습니다.
- 사용자는 배포 화면의 접근키 입력창에 사이트 접근키를 입력합니다. 키는 브라우저 탭 세션에만 보관합니다. 평가자에게는 별도로 전달합니다.

## 검증과 제한

- Render `/health`, `/docs`, Vercel 화면 접속과 CORS를 확인합니다.
- Firestore 읽기 한도가 소진됐다면 서비스가 배포돼도 최신 데이터 조회·AI 저장은 실패할 수 있습니다. 정상 데이터 화면과 CRUD 최종 검증은 할도 복구 후 수행합니다.
- GET 캐시는 서버 로컬 디스크이며 Free 인스턴스 재배포 시 소실될 수 있습니다. Firestore가 원본입니다.
- 크롬 확장은 localhost 전용입니다. 배포 사이트에서는 프로필 자동 화면 수집을 지원한다고 안내하지 않습니다. 공식 API 갱신과 저장된 프로필 마지막 값은 구분합니다.
- 기존 협업은 협업 관리에서 한 번 수정·저장하면 `data/collaboration_{id}`에 분석 기록이 생성됩니다. 신규 협업과 게시물 연결 변경은 같은 트랜잭션으로 분석 기록에 반영됩니다.
- `date`=협업 기준일, `value`=전체 약정 원고료(원), `memo`=협업 메모. 게시물별 방식의 입력 단가는 추가 필드이며 분석 기록의 value는 연결된 게시물 총 원고료입니다. 조회수 합계에는 원고료를 섞지 않습니다.

## 배포 결과

실제 서비스 URL과 검증 결과는 배포 완료 후 README에 기록합니다. 설정 파일 생성이나 GitHub 업로드만으로 배포 완료라고 표시하지 않습니다.
