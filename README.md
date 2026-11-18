# sheet-forge-api

수학 시험지 사진에서 문항을 골라 한글(hwpx) 문제지로 내보내는 서비스 [sheet-forge](https://sheet.tsungmn.com)의 API 서버입니다.

수학 과외 선생님이 학생 시험지에서 틀린 문항만 골라 새 시험지를 만드는 일을 줄이는 것이 목적입니다.

## 할 수 있는 일

- 시험지 사진을 올리면 자동으로 기울기를 바로잡고 문제 칸을 나눕니다
- 선택한 문제를 읽어 글, 수식, 선택지, 그림으로 구조화합니다(외부 LLM 사용)
- 선생님이 화면에서 고친 뒤 확인한 문제만 모아 문제지를 만듭니다
- 문제지를 쪽 설정(용지, 단 수 등)에 맞춰 한글 파일(`.hwpx`)로 내보냅니다. 수식은 한글 수식으로 변환됩니다
- 초대 메일로만 가입하는 로그인, 휴지통(30일), 학생별 문제 검색, 하루 읽기 한도

웹 화면은 [sheet-forge-web](https://github.com/tsungmnli/sheet-forge-web), Kubernetes 배포 설정은 [sheet-forge-config](https://github.com/tsungmnli/sheet-forge-config)에 있습니다.

## 구성

```
브라우저 ── 웹 ──(/api)── API 서버 ──┬── PostgreSQL        데이터
                                    ├── S3 호환 저장소      사진·그림 (MinIO 등)
          작업자 ───────────────────┤── 외부 LLM           사진 분할·문제 읽기 (선택)
                                    └── SMTP               초대·비밀번호 재설정 메일
```

- **API 서버**: FastAPI. 요청을 처리하고 hwpx를 만듭니다.
- **작업자**: 사진 보정, 문제 칸 나누기, 문제 읽기, 그림 정리, 정기 정리를 합니다. API와 같은 코드이고 실행 명령만 다릅니다(`python -m app.worker`).
- 사진 없이 hwpx 내보내기만 쓸 때는 DB와 저장소 없이도 API 서버만으로 동작합니다.

## 내 컴퓨터에서 실행해 보기

필요한 것: Python 3.11 이상, [uv](https://docs.astral.sh/uv/), Docker

```bash
docker compose -f docker-compose.dev.yml up -d   # 개발용 PostgreSQL
cp .env.example .env                              # Windows: copy .env.example .env
uv sync
uv run alembic upgrade head                       # 테이블 만들기
uv run python scripts/dev.py                      # API 서버 + 작업자 함께 실행
```

`http://127.0.0.1:8000/docs`에서 API 문서를 보고 직접 호출해 볼 수 있습니다. 개발 모드에서는 로그인 없이 한 명의 사용자로 동작하고, 사진 인식은 고정된 가짜 결과를 돌려주므로 LLM 키가 없어도 됩니다.

**사진 올리기까지 해 보려면** 로컬 MinIO를 함께 띄우고 `.env`에 주소와 키를 적습니다(주소와 개발용 키는 `docker-compose.dev.yml`에 있습니다).

```bash
docker compose -f docker-compose.dev.yml --profile storage up -d
```

저장소가 없으면 사진 API만 503을 돌려주고 나머지는 동작합니다.

**실제 사진 인식을 쓰려면** `.env`에 `SHEET_FORGE_RECOGNITION_ENGINE=real`과 `SHEET_FORGE_LLM_API_KEY`를 넣고 작업자를 다시 시작하세요.

### DB 없이 hwpx만 만들어 보기

```bash
uv run uvicorn app.api.main:app --reload
```

`request.json`:

```json
{
  "title": "중간고사 1학년 3반",
  "preset": { "columns": { "count": 2 } },
  "problems": [
    {
      "id": "p1",
      "status": "confirmed",
      "content": {
        "stem": [
          { "type": "paragraph", "inlines": [{ "t": "text", "v": "f(x)=5x-1, g(x)=x+3일 때 합성함수의 값을 구하시오." }] }
        ]
      }
    }
  ]
}
```

```bash
curl -X POST "http://127.0.0.1:8000/exports?format=hwpx" \
  -H "Content-Type: application/json" --data @request.json -o out.hwpx
```

PowerShell에서는 `curl.exe`로 쓰세요. 만들어진 `out.hwpx`를 한글에서 열면 됩니다.

## 운영 환경에 배포하기

### 준비물

PostgreSQL, S3 호환 저장소(MinIO 등), 메일 발송용 SMTP(예: Resend), 외부 LLM API 키. HTTPS로 접속할 도메인이 있어야 로그인 쿠키가 동작합니다.

### 이미지 만들기

```bash
docker build -t sheet-forge-api .
```

같은 이미지로 세 가지를 실행합니다. 모두 같은 환경 변수가 필요합니다.

| 하는 일 | 명령 | 비고 |
| --- | --- | --- |
| API 서버 | (이미지 기본 명령) | 8000번 포트, 프로세스 수는 `WEB_CONCURRENCY`(기본 2) |
| 작업자 | `python -m app.worker` | 1개 이상. 없으면 사진이 처리되지 않습니다 |
| DB 마이그레이션 | `alembic upgrade head` | 새 버전을 올릴 때마다, 서버보다 먼저 한 번 |

컨테이너는 비root(uid 10001)로 실행되고, 글꼴은 필요하지 않습니다. Kubernetes용 매니페스트는 [sheet-forge-config](https://github.com/tsungmnli/sheet-forge-config)를 쓰면 됩니다.

### 켜는 순서

1. 환경 변수를 정합니다(아래 표). 운영에서는 **`SHEET_FORGE_AUTH_REQUIRED=1`을 반드시 켭니다.** 끄면 로그인 없이 누구나 한 사용자로 들어옵니다.
2. 마이그레이션을 실행합니다.
3. API 서버와 작업자를 실행합니다.
4. `GET /healthz`(프로세스 상태)와 `GET /readyz`(DB·저장소 연결까지 확인)가 200인지 봅니다.
5. 첫 선생님을 초대합니다(아래 "로그인").

### 환경 변수

모두 `SHEET_FORGE_` 접두어가 붙습니다. 로컬에서는 저장소 루트의 `.env`를 읽고, 이미 설정된 환경 변수가 우선합니다(`.env.example` 참고). 비밀 값은 `.env`나 클러스터 Secret에만 두세요.

**필수**

| 변수 | 설명 |
| --- | --- |
| `DATABASE_URL` | PostgreSQL 주소. `postgresql://사용자:비밀번호@호스트:5432/DB` |
| `MINIO_ENDPOINT` | 저장소 `호스트:포트`. 비우면 사진 API가 503 |
| `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY` | 저장소 접근 키 |
| `AUTH_REQUIRED` | `1`이면 로그인 필요. **운영은 켜기** |
| `WEB_BASE_URL` | 서비스 주소(끝에 `/` 없이). 메일 링크의 앞부분 |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | 초대·재설정 메일. Resend라면 `smtp.resend.com`, `465`, `resend`, API 키, 인증한 도메인의 보내는 주소 |
| `RECOGNITION_ENGINE`, `LLM_API_KEY` | `real`이면 실제 인식(키 필요), 기본 `fake`는 고정된 가짜 결과 |

**선택**

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `DATABASE_URL_RO` | (없음) | 내보내기용 읽기 전용 DB 계정 |
| `DB_POOL_SIZE`, `DB_CONNECT_TIMEOUT_S` | 5, 3 | 연결 풀 크기, 연결 제한 시간(초) |
| `MINIO_BUCKET`, `MINIO_SECURE` | `sheet-forge`, `false` | 버킷 이름(없으면 처음 쓸 때 생성), TLS 사용 여부 |
| `CORS_ORIGINS` | (없음) | 웹이 다른 주소일 때 허용할 Origin(쉼표 구분) |
| `COOKIE_SECURE` | `true` | 세션 쿠키 `Secure`. http로 로컬 개발할 때만 `false` |
| `SESSION_TTL_DAYS` | 30 | 로그인 유지 기간(쓸수록 늘어남) |
| `SEGMENT_MODEL`, `READ_MODEL`, `REREAD_MODEL` | Gemini 계열 | 문제 칸 분할, 읽기, 다시 읽기에 쓰는 모델 |
| `LLM_TIMEOUT_S` | 30 | LLM 호출 제한 시간(초) |
| `DAILY_READ_LIMIT` | 200 | 하루 읽기 한도(한국 시간 기준, 다시 읽기는 2배로 계산) |
| `MAX_PROBLEMS`, `MAX_FIGURES` | 200, 200 | 문제지당 문항·그림 수 상한 |
| `MAX_IMAGE_BYTES`, `MAX_IMAGE_PX` | 5MB, 8000 | 그림 한 장의 크기·변 길이 상한 |
| `MAX_PHOTO_BYTES`, `MAX_PAGES_PER_EXAM` | 20MB, 30 | 사진 한 장 크기, 시험지당 사진 수 상한 |
| `MAX_READ_BATCH` | 50 | 한 번에 읽을 수 있는 문제 수 |
| `MAX_BODY_BYTES` | 32MB | 요청 하나의 크기. 올리면 앞단 프록시의 본문 제한도 같이 올리세요 |
| `WORKER_POLL_S` | 2 | 작업자가 새 작업을 확인하는 간격(초) |
| `MAINTENANCE_INTERVAL_S` | 86400 | 휴지통·원본 사진 정리 간격(초). 0이면 정기 정리 안 함 |

## 로그인 (초대 가입)

가입은 초대로만 합니다. 초대 메일의 링크에서 비밀번호를 정하면 가입과 로그인이 끝납니다. 비밀번호 재설정도 메일 링크로 합니다. 로그인하면 httpOnly 쿠키 `sid`가 생기고, 서버 세션은 쓸수록 만료가 늘어납니다.

```bash
# 내 컴퓨터(.env의 DB·SMTP 설정 사용)
uv run python scripts/invite.py 선생님@example.com
uv run python scripts/reset_password.py 선생님@example.com   # 메일 재설정을 못 쓸 때 직접 바꾸기

# 운영 컨테이너 안에서
python scripts/invite.py 선생님@example.com
```

SMTP를 설정하지 않으면 메일을 보내지 않고 가입 링크를 화면(로그)에 출력합니다. 처음 가입한 사람이 로그인 도입 전에 쌓인 데이터를 이어받습니다.

## API 개요

서비스에서는 모든 경로가 `/api/...`로 보입니다. Ingress(프록시)가 `/api`를 떼고 넘기므로 서버를 직접 호출할 때는 `/api` 없이 씁니다(예: `/exams`). 전체 목록과 요청·응답 모양은 서버를 띄우고 `/docs`(Swagger), `/openapi.json`에서 볼 수 있습니다.

| 경로 | 설명 |
| --- | --- |
| `/auth/*` | 초대 가입, 로그인·로그아웃, 비밀번호 재설정 |
| `/exams`, `/exams/{id}/pages` | 시험지 만들기, 사진 올리기(여러 장) |
| `/exams/{id}/read`, `/problems/{id}` | 문제 읽기, 문제 보기·고치기·확인 |
| `/worksheets`, `/worksheets/{id}/export` | 문제지 만들기·수정, hwpx로 내보내기 |
| `/exports` | 요청에 담은 문항을 바로 hwpx로 내보내기(DB 불필요) |
| `/export-presets` | 쪽 설정(용지·단 수 등) 저장 |
| `/trash` | 휴지통 보기·복구 |
| `/me`, `/home`, `/students` | 내 설정, 홈 화면 요약, 학생 목록 |
| `/healthz`, `/readyz` | 상태 확인 |

오류는 `{ "error": { "code", "message", "details" } }` 형식입니다. 문항 하나의 문제(그림 누락 등)는 오류가 아니라 200 응답의 `report`에 담기고, 내보낼 수 없을 때만 4xx/5xx가 됩니다. 수정 요청은 `If-Match`(버전)가 필요하며, 다른 곳에서 먼저 고쳤다면 412를 돌려줍니다.

## 테스트

```bash
uv run pytest
```

DB가 필요한 테스트는 `SHEET_FORGE_TEST_DATABASE_URL`이 있을 때만 돕니다(테이블을 만들고 지우므로 개발 DB와 다른 DB를 쓰세요). 개발용 compose가 만들어 주는 테스트 DB를 쓰려면 `.env`에 아래를 적습니다.

```
SHEET_FORGE_TEST_DATABASE_URL=postgresql://postgres:dev@127.0.0.1:5432/sheet_forge_test
```

변경 사항이 hwpx 모양에 영향을 주는지 눈으로 보려면 `uv run python scripts/make_smoke.py smoke`로 확인용 파일을 만들어 한글에서 열어 보세요.

## 제한 사항

- 굵게·밑줄 같은 글자 서식은 hwpx에 반영되지 않고 내보내기 리포트로만 알려 줍니다.
- 선택지 번호는 ①~⑤까지 지원하고, `<보기>`와 표가 들어간 문항은 지원하지 않습니다.
- 수식 크기는 한글 한 가지 버전에서 확인한 규칙을 따릅니다. 다른 버전에서는 모양이 조금 다를 수 있습니다.
- 문제 읽기는 외부 LLM의 결과라 글자가 빠지거나 잘못 읽힐 수 있습니다. 그래서 선생님이 확인한 문제만 문제지에 담을 수 있게 되어 있습니다.
- 그림 정리는 색 필기만 지웁니다. 검정·연필 필기는 지우지 못합니다.
- 로그인 시도 횟수 제한과 소셜 로그인(Google, 카카오)은 없습니다.
- 인식 엔진이 `real`이면 시험지 사진의 축소본과 문제 부분 이미지가 외부 LLM 서비스로 전송됩니다. 서비스를 공개할 때는 약관과 개인정보 안내를 준비하세요.
