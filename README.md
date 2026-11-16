# sheet-forge-api

시험지 문항 데이터를 한글(hwpx) 파일로 내보내는 FastAPI 서버입니다.
문항(텍스트·수식·선택지·그림)과 쪽 설정(preset)을 받아 hwpx 파일과 내보내기 리포트를 돌려줍니다.

수학 과외 선생님이 시험지 사진에서 틀린 문항만 골라 새 시험지를 만드는 작업을 줄이려는 프로젝트 `sheet-forge`의 API 부분입니다. 이 저장소는 내보내기 기능만 다루며, 사진 인식이나 문항 편집 화면은 포함하지 않습니다.

## 구성

```
app/
  api/               FastAPI 앱 (라우터, 요청 모델, 오류 매핑, 설정)
  export/hwpx/       hwpx 생성 라이브러리 (무상태, I/O 없음)
  export/math/       LaTeX → 한글 수식 스크립트 변환기
assets/templates/    빈 hwpx 템플릿 (blank.hwpx)
scripts/             스모크 hwpx 생성, 수식 폭 재피팅
tests/               pytest
Dockerfile
```

API 층은 얇게 두고, 내보내기 로직은 `app/export/hwpx`에 있습니다. 라이브러리는 같은 입력이면 같은 바이트를 만들도록 되어 있습니다(ID는 카운터, zip 항목 시각 고정, 메타 시각은 입력으로 받음).

설계 문서는 `docs/`에 있습니다.

- `hwpx-export-design.md`: hwpx 생성 모듈 설계
- `export-api-design.md`: HTTP API 설계

## 개발 환경

필요한 것: Python 3.11 이상 권장(`pyproject.toml`의 `requires-python`은 `>=3.10`), [uv](https://docs.astral.sh/uv/).

```bash
uv sync          # 런타임 + dev 의존성 설치 (.venv 생성)
uv run pytest    # 테스트
```

uv 없이 pip를 쓸 때:

```bash
python -m venv .venv
source .venv/bin/activate      # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
pytest
```

참고:

- dev 의존성의 `httpx2`는 Python 3.11 이상에서만 설치됩니다. 3.10에서는 `httpx`가 대신 설치됩니다. FastAPI `TestClient`가 필요로 합니다.
- 캐시와 프로젝트가 다른 드라이브에 있는 Windows에서는 uv가 하드링크 경고를 냅니다. `pyproject.toml`의 `link-mode = "copy"` 설정으로 조용해집니다.
- `scripts/fit_math_width.py`를 쓸 때만 `numpy`, `scipy`가 필요합니다: `uv sync --group fit`

### 서버 실행

```bash
uv run uvicorn app.api.main:app --reload
```

기본 주소는 `http://127.0.0.1:8000`입니다. 자동 생성 문서는 `/docs`에서 볼 수 있습니다.

```bash
curl http://127.0.0.1:8000/healthz      # liveness. 외부 의존성을 보지 않는다
curl http://127.0.0.1:8000/readyz       # readiness. 템플릿 로드 여부를 확인한다
```

### 내보내기 호출 예

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

hwpx 파일을 바로 받으려면 `format=hwpx`를 붙입니다. 요약은 응답 헤더(`X-Export-Status` 등)에 담깁니다.

```bash
curl -X POST "http://127.0.0.1:8000/v1/exports?format=hwpx" \
  -H "Content-Type: application/json" --data @request.json -o out.hwpx
```

PowerShell에서는 `curl`이 `Invoke-WebRequest`의 별칭이라 `curl.exe`로 써야 합니다.

`format`을 생략하면 리포트와 파일(base64)이 한 JSON 응답으로 옵니다. 쪽 설정으로 계산된 본문 폭과 단 폭만 확인하려면 `POST /v1/exports/layout-preview`, 기본 preset은 `GET /v1/export-presets/defaults`로 볼 수 있습니다.

### 엔드포인트

| 메서드·경로 | 설명 |
| --- | --- |
| `POST /v1/exports` | hwpx 내보내기. 기본은 JSON(리포트 + base64 파일), `?format=hwpx`는 바이너리 |
| `POST /v1/exports/layout-preview` | preset으로 계산한 본문 폭·단 폭 |
| `GET /v1/export-presets/defaults` | 기본 preset과 용지 후보 |
| `GET /healthz`, `GET /readyz` | liveness, readiness |

오류는 `{ "error": { "code", "message", "details" } }` 형식입니다. 문항 단위의 문제(그림 누락 등)는 오류가 아니라 200 응답의 `report`에 담기고, 내보낼 수 없는 경우(잘못된 preset, 내보낼 문항 없음 등)만 4xx/5xx입니다. 자세한 매핑은 `docs/export-api-design.md` 5장에 있습니다.

현재는 요청 본문에 문항과 이미지(base64 PNG)를 직접 담는 방식만 구현되어 있습니다. DB(`problem_ids`) 연동은 이후 단계입니다.

### 설정

환경 변수로 바꿉니다. 값을 올리면 앞단 프록시의 본문 크기 제한도 함께 확인해야 합니다.

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `SHEET_FORGE_MAX_PROBLEMS` | 200 | 문항 수 상한 |
| `SHEET_FORGE_MAX_FIGURES` | 200 | 그림 개수 상한 |
| `SHEET_FORGE_MAX_IMAGE_BYTES` | 5242880 | 이미지 한 장의 디코딩 후 크기(5MB) |
| `SHEET_FORGE_MAX_IMAGE_PX` | 8000 | 이미지 한 변의 픽셀 상한 |
| `SHEET_FORGE_MAX_BODY_BYTES` | 33554432 | 요청 본문 크기(32MB) |
| `SHEET_FORGE_CORS_ORIGINS` | (비어 있음) | 허용할 웹 Origin, 쉼표로 구분 |
| `SHEET_FORGE_DATABASE_URL` | (비어 있음) | Postgres 쓰기 계정 주소. 비어 있으면 DB 없이 동작 |
| `SHEET_FORGE_DATABASE_URL_RO` | (비어 있음) | 내보내기용 읽기 계정 주소. 비어 있으면 위 주소를 씀 |
| `SHEET_FORGE_DB_POOL_SIZE` | 5 | 연결 풀 크기 |
| `SHEET_FORGE_DB_CONNECT_TIMEOUT_S` | 3 | DB 연결 제한 시간(초) |
| `SHEET_FORGE_DEFAULT_OWNER_ID` | owner_default | 인증 전 단일 소유자 |
| `SHEET_FORGE_MINIO_ENDPOINT` | (비어 있음) | MinIO `호스트:포트`. 비어 있으면 사진 API는 503 |
| `SHEET_FORGE_MINIO_ACCESS_KEY` / `_SECRET_KEY` | (비어 있음) | MinIO 접근 키 |
| `SHEET_FORGE_MINIO_BUCKET` | sheet-forge | 버킷 이름(없으면 처음 쓸 때 만듦) |
| `SHEET_FORGE_MINIO_SECURE` | false | TLS 사용 여부 |
| `SHEET_FORGE_MAX_PHOTO_BYTES` | 20971520 | 사진 한 장 상한(20MB) |
| `SHEET_FORGE_MAX_PAGES_PER_EXAM` | 30 | 시험지당 사진 상한 |
| `SHEET_FORGE_MAX_READ_BATCH` | 50 | 한 번에 읽을 수 있는 문제 수 |
| `SHEET_FORGE_DAILY_READ_LIMIT` | 200 | 하루 읽기 한도(한국 시간 기준, 다시 읽기는 2배). 값은 운영하며 조정 |
| `SHEET_FORGE_RECOGNITION_ENGINE` | fake | `fake`(가짜, 고정 결과) 또는 `real`(실제 보정·분할·읽기·그림 정리). 작업자가 시작할 때 한 번 정함 |
| `SHEET_FORGE_LLM_API_KEY` | (비어 있음) | 외부 LLM 키. `real`이면 필수(그림 정리만은 키가 필요 없음). Secret으로만 넣음 |
| `SHEET_FORGE_SEGMENT_MODEL` | gemini-3.5-flash-lite | 문제 칸 분할 모델 |
| `SHEET_FORGE_READ_MODEL` | gemini-3.5-flash-lite | 기본 읽기 모델 |
| `SHEET_FORGE_REREAD_MODEL` | gemini-3.8-flash | 다시 읽기 모델 |
| `SHEET_FORGE_LLM_TIMEOUT_S` | 30 | LLM 호출 제한 시간(초) |
| `SHEET_FORGE_SEGMENT_IMAGE_LONG_SIDE` | 1500 | 분할 호출에 보내는 이미지의 긴 변(px) |
| `SHEET_FORGE_WORKER_POLL_S` | 2 | 작업자가 새 작업을 확인하는 간격(초) |
| `SHEET_FORGE_MAINTENANCE_INTERVAL_S` | 86400 | 작업자의 정기 정리 간격(초). 시작 직후 한 번 실행하고 그 뒤 이 간격마다 실행하며, 0이면 정기 정리를 하지 않음 |
| `WEB_CONCURRENCY` | 2 | uvicorn 워커 수 (Docker 이미지 기본값) |

### DB와 마이그레이션 (B0)

웹 REST API(`docs/rest-api-design.md`)가 쓰는 Postgres 연결 기반입니다. `SHEET_FORGE_DATABASE_URL`이 비어 있으면 DB 없이 동작합니다(내보내기만 쓰는 개발·테스트).

- 쓰기는 `database_url`, 내보내기 경로의 읽기는 `database_url_ro`(없으면 같은 계정)를 쓰고, 읽기 세션은 항상 `SET TRANSACTION READ ONLY`로 시작합니다.
- `/readyz`가 DB 연결을 확인합니다. DB가 내려가면 `/readyz`는 503이 되고 `/healthz`는 200을 유지합니다. DB 오류는 `503 DB_UNAVAILABLE`(`retryable: true`)로 응답합니다.
- 쓰기는 서비스 함수가 `session.commit()`을 직접 호출합니다(의존성이 자동 커밋하지 않습니다). 수정은 `app/api/repo.py`의 `update_versioned`(낙관적 잠금), 삭제는 `soft_delete`를 씁니다.
- 새 테이블은 `app/db/base.py`의 `CommonColumns`(id·owner_id·version·시각·소프트 삭제)를 상속하고, ID는 `app/db/ids.py`의 `new_id("exam")` 같은 호출로 만듭니다.

```bash
docker compose -f docker-compose.dev.yml up -d   # 개발용 Postgres (DB: sheet_forge, 테스트용: sheet_forge_test)
cp .env.example .env        # Windows: copy .env.example .env (필요하면 .env 안의 값을 고친다)
uv run alembic upgrade head
```

`docker-compose.dev.yml`은 로컬 개발 전용이고 127.0.0.1에만 열립니다(비밀번호 `dev`). `sheet_forge_test`는 볼륨을 처음 만들 때만 생성되며, 처음부터 다시 만들려면 `docker compose -f docker-compose.dev.yml down -v` 뒤 `up -d`를 합니다. 테스트가 DB 통합 테스트를 건너뛰지 않게 하려면 `.env`에 `SHEET_FORGE_TEST_DATABASE_URL=postgresql://postgres:dev@127.0.0.1:5432/sheet_forge_test`를 켭니다. 사진 업로드까지 로컬에서 시험하려면 `docker compose -f docker-compose.dev.yml --profile storage up -d`로 로컬 MinIO(API 9000, 콘솔 9001, 계정 `devadmin` / `devadmin-secret`)를 띄우고 `.env`에 `SHEET_FORGE_MINIO_ENDPOINT=127.0.0.1:9000`, `SHEET_FORGE_MINIO_ACCESS_KEY=devadmin`, `SHEET_FORGE_MINIO_SECRET_KEY=devadmin-secret`을 적습니다(버킷은 처음 쓸 때 만들어집니다).

서버와 Alembic은 저장소 루트의 `.env`를 자동으로 읽습니다(항목은 `.env.example`). 터미널·클러스터에 같은 이름의 환경 변수가 이미 있으면 그 값이 우선하고, `.env`는 git에 올라가지 않습니다. 클러스터에서는 Secret·ConfigMap의 환경 변수를 씁니다.

클러스터에서는 같은 이미지로 `alembic upgrade head`를 Job(또는 initContainer)으로 한 번 실행합니다. DB 통합 테스트는 `SHEET_FORGE_TEST_DATABASE_URL`(테스트 전용 DB, 테이블을 만들고 지웁니다)을 지정하면 돌고, 없으면 건너뜁니다. CI는 Postgres 서비스를 띄워 같이 돌립니다.

### 시험지·사진 API와 작업자 (B1)

- API: `/v1/exams`(CRUD, 수정은 `If-Match`), `/v1/exams/{id}/pages`(업로드는 multipart 필드 이름 `files`, 여러 장), `/v1/pages/{id}`, `/v1/images/{ref}`. 사진은 MinIO에 두고 DB에는 참조(`img_…`)만 둡니다. 자동 생성 문서는 `/docs`, 스펙은 `/openapi.json`입니다.
- 작업자: `python -m app.worker`(API와 같은 이미지, 실행 명령만 다름). `jobs` 테이블을 `FOR UPDATE SKIP LOCKED`로 가져가고, 실패하면 2번 지연 재시도한 뒤 사진을 `failed`로 표시합니다. 기본은 가짜 `PageProcessor`(고정 칸 6개)이고, `SHEET_FORGE_RECOGNITION_ENGINE=real`이면 실제 구현을 씁니다(아래 B5 절). 작업자에도 `.env`와 같은 DB·MinIO 설정이 필요합니다.
- MinIO 설정이 없으면 사진 API만 503이고 시험지 API는 그대로 동작합니다. `/readyz`에는 `storage` 점검이 추가됩니다.
- 요청 하나의 크기 제한은 `SHEET_FORGE_MAX_BODY_BYTES`(기본 32MB)입니다. 사진이 많으면 여러 요청으로 나눠 올립니다.
- HEIC는 받아서 저장하지만 브라우저가 바로 보여 주지 못합니다. 보정본(JPEG)을 만드는 B5-1 전까지는 미리보기가 안 될 수 있습니다.

### 문제 칸·문제 API와 작업자 (B2)

- **문제 칸**: `PATCH /v1/pages/{id}/segments/{sid}`(고르기/해제), `PUT /v1/pages/{id}/segments`(칸 전체 교체, `id`가 있는 칸은 유지), `POST /v1/exams/{id}/segments/mark`(한꺼번에 고르기/해제. 범위는 `segment_ids` 또는 `page_id`, 둘 다 없으면 시험지 전부이며 둘을 함께 보내면 422). 읽은 문제가 있는 칸은 해제·삭제할 수 없고 `409 SEGMENT_HAS_PROBLEM`입니다(`mark`는 해제하지 않고 `skipped`로 셉니다).
- **읽기**: `POST /v1/exams/{id}/read`(202, 본문을 생략하면 읽지 않은 고른 칸 전부. 이미 읽은 칸은 건너뜀, 한 번에 `SHEET_FORGE_MAX_READ_BATCH`개까지), `GET /v1/exams/{id}/problems?state=`(고른 칸 목록이고 읽기 전 칸은 `not_read`). 하루 읽기 한도(`SHEET_FORGE_DAILY_READ_LIMIT`, 한국 시간 기준, 다시 읽기는 2배로 셈)를 넘으면 `429 READ_LIMIT`이고 일부만 읽히지 않습니다.
- **문제**: `GET /v1/problems/{id}`(`ETag`), `PUT …/content`(자동 저장, `If-Match` 필수: 없으면 428, 낡았으면 412 `VERSION_CONFLICT`), `POST …/confirm`(`If-Match` 필수. 변환할 수 없는 수식이 있으면 `409 MATH_UNSUPPORTED`와 `details[{path, message}]`, 내용이 비었으면 `422 EMPTY_PROBLEM`), `POST …/reopen`·`…/revert`·`…/reread`(202), `DELETE`, `GET …/neighbors`. 상태는 `recognizing → needs_review ↔ confirmed`이고 읽기에 실패하면 `failed`입니다(그래도 직접 입력해 확인할 수 있습니다). 응답에는 항상 `hints`(여기부터 보세요)와 `checks`(확인 완료 가능 여부와 막는 이유)가 들어 있고 저장되지 않으며 읽을 때마다 계산합니다.
- **그림**: `POST …/figures`(202), `PUT …/figures/{fid}/region`(202), `DELETE …/figures/{fid}`. 크롭·정리는 작업자가 하고 그림 `state`는 `processing → ready`(실패하면 `failed`)입니다. 정리만 실패하면 원본 그림을 씁니다(`use="raw"`). 그림은 서버가 관리하므로 본문 저장에서는 `use`·`placement`·`width_mm`만 바꿀 수 있고, 모르는 그림이나 남의 `ref`는 `422 FIGURE_REF_INVALID`입니다.
- **수식 점검**: `POST /v1/math/check`(요청당 200개, DB 없음, 한글 수식 스크립트는 돌려주지 않고 `status`·`message`·`est_width`만).
- **작업자**: `problem_read`·`problem_reread`·`figure_clean`을 처리합니다. 읽는 사이 문제가 지워지거나 상태가 바뀌면 결과를 버리고 만들던 크롭 이미지를 정리하며, 마지막 시도까지 실패하면 `failed`로 표시합니다. 기본은 가짜 `Recognizer`(고정 문제)와 가짜 `FigureCleaner`(정리 없음)이고, `SHEET_FORGE_RECOGNITION_ENGINE=real`이면 실제 구현을 씁니다(아래 B5 절). `recognized`(되돌리기 기준)는 기계가 읽을 때마다 덮어씁니다(다시 읽기 결과가 새 기준).
- **DB**: 마이그레이션 `0003`(`problems`, `read_usage`). 한 칸에 살아 있는 문제는 하나입니다(부분 유니크 인덱스).

### 문제지·저장된 모양 API (B3 완료)

- **문제지**: `POST/GET /v1/worksheets`, `GET/PATCH/DELETE /v1/worksheets/{id}`, `PUT/POST /v1/worksheets/{id}/problems`, `POST …/duplicate`. `from_exam_id`로 만들면 그 시험지의 확인 완료 문제를 사진 순서대로 담고 학생을 이어받습니다. `PATCH`·`PUT problems`는 `If-Match` 필수(428·412), 뒤에 추가하는 `POST problems`는 필요 없지만 `version`은 올라갑니다. 담을 수 있는 문제 수는 `SHEET_FORGE_MAX_PROBLEMS`(413 `TOO_MANY_PROBLEMS`).
- **번호**: 서버가 계산합니다. 삭제된 문제는 번호가 없고, `unconfirmed_policy="skip"`이면 확인 안 끝난 문제도 번호가 없습니다(`fail`이면 번호가 붙음). 내보내기와 같은 규칙입니다.
- **모양**: 문제지는 모양(preset)을 값으로 복사해 갖습니다. `PATCH`에 `preset`(값) 또는 `preset_id`(저장된 모양, 둘 중 하나)를 보내며, 잘못된 값은 422 `PRESET_INVALID`입니다. 응답의 `layout`은 본문 폭·칸 폭입니다.
- **저장된 모양**: `GET/POST /v1/export-presets`, `PUT/DELETE /v1/export-presets/{id}`(`PUT`은 `If-Match`). 내장 모양 `builtin_a4_1col`("A4 한 칸"), `builtin_b5_2col`("B5 두 칸", 182×257mm)은 코드 상수라 고치거나 지울 수 없습니다(409 `PRESET_BUILTIN`).
- **문제 검색**: `GET /v1/problems?status=&student=&exam_id=&q=&worksheet_id=`(기본은 확인 완료). `worksheet_id`를 주면 이미 담긴 문제에 `in_worksheet`가 표시됩니다. `q`는 부분 일치(`ilike`)이고 `pg_trgm` 인덱스는 아직 없습니다.
- **점검**: `GET /v1/worksheets/{id}/check`. 파일을 만들지 않고 `ready`와 항목(`EMPTY_EXPORT`·`UNCONFIRMED_BLOCKS`·`PRESET_INVALID`는 오류, `UNCONFIRMED`·`DELETED`·`FIGURE_MISSING`은 경고)을 돌려줍니다.
- **DB**: 마이그레이션 `0004`(`worksheets`, `worksheet_items`, `export_presets`). 4단계에서 마이그레이션 변경은 없습니다.
- **내보내기**: `POST /v1/worksheets/{id}/export?format=json|hwpx`. 문제지에 담긴 문제를 담은 순서대로 읽고(삭제된 문제는 제외) 그림은 이미지 저장소에서 가져와 hwpx를 만듭니다. 응답은 `POST /v1/exports`와 같습니다(JSON은 리포트 + base64 파일, `hwpx`는 바이너리와 `X-Export-*` 헤더). 문제 읽기는 읽기 전용 세션, 성공한 뒤 `last_export {at, name, status}` 기록은 쓰기 세션이 하며 `version`·`updated_at`은 올리지 않습니다. 문제지의 `unconfirmed_policy`가 모양의 `on_unconfirmed`보다 우선합니다. `skip`이면 확인 안 된 문제는 `NOT_CONFIRMED` 경고와 함께 빠지고 번호도 건너뛰며, `fail`이면 409 `NOT_CONFIRMED`입니다. 담긴 문제가 없으면 422 `EMPTY_EXPORT`, 문제·그림 수 한도를 넘으면 413입니다. 리포트 항목에 `problem_id`가 있으면 `link {exam_id, problem_id}`를 붙입니다. 그림을 못 찾거나 불러오지 못하면 그 문제는 빠지고 리포트로 알립니다. 파일은 보관하지 않습니다. 문제지 `header`(이름란·날짜란 등)는 아직 파일에 반영하지 않습니다.

### 휴지통·설정·홈·정기 정리 (B4 완료)

- **삭제와 휴지통**: 시험지·사진을 지우면 그 안의 문제도 `deleted_with`로 묶어 휴지통에 보냅니다(목록·검색·문제지에서 빠짐). `GET /v1/trash?type=`는 시험지·사진·문제·문제지 목록과 `purge_at`(30일 뒤)을 줍니다.
- **복구**: `POST /v1/trash/{type}/{id}/restore`. 같이 지운 것만 복구하고, 부모가 휴지통에 있으면 409 `PARENT_IN_TRASH`입니다. 따로 지운 문제는 그대로 둡니다.
- **내 설정**: `GET /v1/me`, `GET`·`PATCH /v1/me/settings`. 잘못된 값은 422입니다. `student_name_display`는 `full`·`alias`·`masked`, 원본 사진 보존 기간은 7·30·90일과 계속 보관입니다. 마이그레이션 `0005`(`user_settings`).
- **홈**: `GET /v1/home`(상태별 할 일 수와 `next_problem`), `GET /v1/students`.
- **정기 정리**: 작업자가 `purge_trash`(30일 지난 항목과 이미지 영구 삭제)와 `purge_originals`(원본 사진만 보존 기간 뒤 삭제, 기본 30일, 사용자 설정이 우선)를 실행합니다. 원본이 없으면 보정 다시 하기는 409 `ORIGINAL_EXPIRED`입니다. 로그에는 종류별 개수만 남깁니다.
  - 시작 직후 한 번, 그 뒤 `SHEET_FORGE_MAINTENANCE_INTERVAL_S`마다 실행합니다. 실패해도 오류 종류만 로그에 남기고 작업 처리는 계속합니다.
  - 작업자가 여러 개면 각자 실행합니다. 지우는 조건이 겹치지 않고 두 번 실행해도 결과가 같아 잠금은 없습니다.
  - 작업자를 재시작할 때마다 정리가 한 번 돕니다.
- **알려 둘 것**: 이 변경 전에 지운 개발·테스트 데이터의 문제는 마이그레이션하지 않았습니다.

### 인식 파이프라인 (B5 완료)

- **전환**: `SHEET_FORGE_RECOGNITION_ENGINE`이 `fake`(기본)이면 가짜 처리기·인식기·그림 정리기를, `real`이면 실제 구현을 씁니다. 작업자가 시작할 때 한 번 정하므로 바꾸면 작업자를 다시 시작해야 합니다. `real`이면 `SHEET_FORGE_LLM_API_KEY`가 필요하고(없으면 시작할 때 종료), 그 밖의 값이어도 시작할 때 종료합니다. 그림 정리만은 키가 필요 없습니다.
- **사진 처리**(`page_process`): 보정(OpenCV, 원근·기울기)한 뒤 LLM에 문제 칸을 한 번 제안받고, 로컬 후처리(가장자리 맞춤)를 합니다. 분할이 실패하거나 문제가 하나도 없으면 열 분할로 대신하고 `processing.message`로 선생님께 알립니다(로그에는 종류만).
- **읽기**(`problem_read`·`problem_reread`): 문제 칸 크롭 한 장을 LLM에 한 번 보내 구조(문단·수식 조각·선택지)로 받습니다. 저장하기 전에 후처리(이스케이프 복구, 문장 속 변수 수식화, 수식 안 한글 분리, 줄 끝에서 쪼개진 문단 합치기)를 하고, 수식 변환기로 검증해 변환할 수 없는 수식은 텍스트 전용 수리 호출을 최대 한 번 합니다. 기본 읽기는 `READ_MODEL`, 다시 읽기는 `REREAD_MODEL`을 씁니다.
- **그림 정리**(`figure_clean`): LLM 없이 OpenCV로 조명 평탄화와 색 필기 제거를 합니다. 잉크가 정리 전의 40% 미만으로 줄면 과제거로 보고 원본 그림을 씁니다.
- **프롬프트**: `app/recognition/prompts/`의 `segment_v2.md`·`read_v3.md`·`repair_v1.md`. 읽기 프롬프트의 `{{VOCAB}}`는 수식 변환기가 지원하는 어휘로 채웁니다.
- **사용량 기록**: LLM 호출 한 번이 `usage_events` 한 줄입니다(`call`은 segment·read·repair, 모델, 입력·출력·추론 토큰, 지연). 문제 내용·이미지·프롬프트는 저장하지 않습니다. 호출 직후 별도 트랜잭션으로 기록하므로 읽는 사이 문제가 지워져 결과를 버려도 남고, 기록이 실패해도 작업은 계속합니다. 마이그레이션 `0007`. 월 비용은 이 표를 합산해 봅니다(웹에는 노출하지 않음).
- **계측**: 문제를 확인(`confirm`)할 때 기계가 읽은 결과(`recognized`)와 확인한 내용을 비교해 고친 조각 수를 `ocr_meta.edits`에 남깁니다: `{"edited": {text, math, choices, paragraphs}, "of": {…}}`(숫자만, 공백 차이는 고친 것으로 세지 않음). 직접 입력한 문제는 건너뛰고, 다시 읽기를 하면 `ocr_meta`가 새로 덮어써져 확인할 때 새 기준으로 다시 셉니다. 그림은 비교할 기준이 없어 세지 않습니다.
- **한도**: 하루 읽기 한도는 `usage_events`가 아니라 B2의 `read_usage`로 셉니다(한 문장으로 원자적으로 세기 위해). 분할·수리 호출은 한도에 들지 않습니다.
- **개인정보·로그**: `real`일 때 분할에서는 보정한 사진의 축소본(긴 변 `SEGMENT_IMAGE_LONG_SIDE`)이, 읽기에서는 문제 크롭이 외부 LLM 공급자로 나갑니다. 로그에는 종류·모델·예외 이름만 남깁니다.
- **임시로 정한 것**(설계에 값이 없음): 한도를 `read_usage`로 세는 것, 읽기가 LLM 호출 전에 실패해도 센 한도를 돌려주지 않는 것, 사용량을 별도 트랜잭션으로 기록하는 것, 계측 항목 4종과 그림 제외, 분할이 알려 준 선택지·그림 영역을 아직 저장하지 않는 것(`SegmentDraft`에 담기만 함).
- **알려 둘 것**: `REREAD_MODEL` 기본값 `gemini-3.8-flash`는 2027-01-01부터 가격이 두 배가 됩니다(설계 문서 실측 기준). 그 전에 `usage_events`로 사용량을 보고 모델을 정하세요.

### 테스트

```bash
uv run pytest
```

테스트 파일은 단계별로 나뉘어 있습니다.

| 파일 | 대상 |
| --- | --- |
| `test_api.py` | 엔드포인트 계약, 오류 매핑, 결정성, 로그 비노출 |
| `test_m1.py` ~ `test_m6.py` | hwpx 생성 모듈(뼈대, 수식, 선택지, 그림, 쪽 설정, 리포트·검증) |
| `test_math.py`, `test_math_wrap.py` | 수식 변환기와 줄바꿈 |
| `test_b0.py` | ID, 낙관적 잠금, 쉬운 문장 표, DB 장애 503, DB 통합(환경 변수 있을 때) |
| `test_b1.py` | 시험지·사진 API, 작업 큐·작업자, 이미지 저장소(DB 통합은 환경 변수 있을 때) |
| `test_b2.py` | 문제 칸·문제 API, 읽기 작업자, 그림, 읽기 한도(DB 통합은 환경 변수 있을 때) |
| `test_b3.py` | 문제지 CRUD·담기·순서·번호 계산(DB 통합은 환경 변수 있을 때) |
| `test_b3_presets.py` | 저장된 모양 CRUD, 내장 모양, 문제지 `preset_id` |
| `test_b3_tools.py` | 문제 검색, 문제지 점검 |
| `test_b3_export.py` | 문제지 내보내기(JSON·hwpx, `last_export`, 오류), 저장소 이미지 어댑터, 리포트 `link` |
| `test_b4_*.py` | 휴지통·복구·설정·홈·정기 정리(`test_b4_maintenance.py`: 보존 기간과 영구 삭제) |

수식 변환 테스트는 `tests/fixtures/math_gallery_v*_results.json`(한글에서 직접 측정한 결과)을 기준으로 합니다.

### 스모크 파일과 한글에서의 확인

단위 테스트는 파일이 구조적으로 유효한지만 확인합니다. 실제로 한글에서 열었을 때의 모습은 사람이 봐야 하므로, 확인용 hwpx를 만드는 스크립트가 있습니다.

```bash
uv run python scripts/make_smoke.py smoke
```

`smoke/`에 만들어진 파일을 한글에서 열어 확인합니다. 이 폴더는 `.gitignore`에 들어 있습니다.

### 수식 폭 추정 재피팅

선택지 열 수와 수식 줄바꿈은 수식 폭 추정에 의존합니다. 추정 상수를 다시 맞춰야 할 때만 씁니다.

```bash
uv run python scripts/fit_math_width.py            # 현재 상수의 오차 확인
uv run --group fit python scripts/fit_math_width.py --fit --cv
```

결과는 `app/export/math/emit.py`의 `W`에 직접 옮겨 적습니다.

## Docker

```bash
docker build -t sheet-forge-api .
docker run --rm -p 8000:8000 sheet-forge-api
```

이미지에는 앱과 `assets/templates/blank.hwpx`만 들어갑니다. 글꼴은 한글이 사용자 PC에서 해석하므로 필요하지 않습니다. 컨테이너는 non-root(uid 10001)로 실행됩니다.

## 배포

`main`에 push하면 GitHub Actions(`.github/workflows/deploy.yml`)가 테스트를 돌리고, 이미지를 빌드해 Docker Hub(`tsungmn/sheet-forge-api`)에 올린 뒤, 인프라 저장소 `sheet-forge-infra`의 이미지 태그를 갱신합니다. 이후 배포는 ArgoCD가 맡습니다. 매니페스트와 첫 배포 절차는 인프라 저장소의 `config/README.md`에 있습니다.

## 알려진 제한

- 외부에 공개하기 전에 인증이 필요합니다(앞단 인증 권장). 현재 API 자체에는 인증이 없습니다.
- 굵게·밑줄 같은 텍스트 서식은 내보내지 않고 리포트로만 알립니다.
- 문제지 `header`(이름란·날짜란 등)는 내보낸 파일에 아직 반영되지 않습니다.
- 선택지 마커는 ①~⑤까지, `<보기>`와 표가 들어간 문항은 지원하지 않습니다.
- 수식 크기 지정 방식은 한 가지 한글 버전에서 확인한 규칙을 따릅니다. 다른 버전에서의 호환은 확인이 더 필요합니다.
- 읽기는 외부 LLM 결과라 사진에 없는 글이 들어가거나 글자가 빠질 수 있습니다. 그래서 선생님이 보고 고친 뒤 확인하는 흐름입니다.
- 그림 정리는 색 필기만 지웁니다. 검정·연필 필기는 지우지 못합니다.
- 분할이 알려 준 선택지·그림 영역은 아직 저장하지 않습니다.
- `SHEET_FORGE_RECOGNITION_ENGINE=real`이면 사진 축소본과 문제 크롭이 외부 LLM 공급자로 전송됩니다. 이용약관·개인정보 안내는 외부 공개 전에 정리해야 합니다.
