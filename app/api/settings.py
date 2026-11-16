"""API 설정 (설계 6장). 환경 변수 SHEET_FORGE_* 로 바꿀 수 있다."""
import os
from dataclasses import dataclass

from ..envfile import load_env_file


@dataclass(frozen=True)
class Settings:
    max_problems: int = 200
    max_figures: int = 200
    max_image_bytes: int = 5 * 1024 * 1024
    max_image_px: int = 8000
    max_body_bytes: int = 32 * 1024 * 1024
    cors_origins: tuple = ()
    # B0: DB (웹 REST API 설계 D1·D3). database_url이 비어 있으면 DB 없이 동작한다(내보내기만 쓰는 개발·테스트).
    database_url: str = ""
    database_url_ro: str = ""             # 내보내기 경로용 읽기 계정. 비어 있으면 database_url을 쓴다
    db_pool_size: int = 5
    db_connect_timeout_s: int = 3
    # B1: 이미지 저장소(MinIO)와 사진 제한 (웹 REST API 설계 D4·9장)
    minio_endpoint: str = ""             # 호스트:포트. 비어 있으면 저장소 없이 동작(사진 API는 503)
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket: str = "sheet-forge"
    minio_secure: bool = False           # TLS(https) 사용 여부
    max_photo_bytes: int = 20 * 1024 * 1024
    max_pages_per_exam: int = 30
    # B2: 문제 읽기 (웹 REST API 설계 5.4·9장)
    max_read_batch: int = 50           # 한 번에 읽기 최대 문제 수
    trash_retention_days: int = 30      # 휴지통 보관 일수(설계 5.9, web-design A2-7). 지나면 작업자가 영구 삭제(B4-6)
    daily_read_limit: int = 200        # 하루 읽기 한도(다시 읽기는 2배 가중). 설계 13장 8번(1인 하루 200문제), 엔진 단가가 정해지면 조정
    default_owner_id: str = "owner_default"  # 인증 전 단일 소유자(D3). 인증이 정해지면 deps.current_user가 대신한다
    # B5-2a: LLM 공급자 (인식 파이프라인 설계 8.3). 키는 Secret으로만 넣는다(이미지·저장소에 두지 않음)
    llm_api_key: str = ""
    segment_model: str = "gemini-3.5-flash-lite"
    read_model: str = "gemini-3.5-flash-lite"
    reread_model: str = "gemini-3.8-flash"
    llm_timeout_s: int = 30
    recognition_engine: str = "fake"   # B5-2c: fake | real. real이면 보정·분할에 실제 구현을 쓴다(LLM_API_KEY 필요)
    segment_image_long_side: int = 1500  # 분할 호출에 보내는 이미지의 긴 변(px)

    @classmethod
    def from_env(cls, env=None) -> "Settings":
        if env is None:
            load_env_file()  # 저장소 루트의 .env (이미 설정된 환경 변수가 우선)
            env = os.environ
        d = cls()

        def num(name, default):
            v = env.get(f"SHEET_FORGE_{name}")
            return int(v) if v not in (None, "") else default

        def text(name, default):
            v = env.get(f"SHEET_FORGE_{name}")
            return v.strip() if v not in (None, "") else default

        origins = env.get("SHEET_FORGE_CORS_ORIGINS", "")
        return cls(max_problems=num("MAX_PROBLEMS", d.max_problems), max_figures=num("MAX_FIGURES", d.max_figures),
                   max_image_bytes=num("MAX_IMAGE_BYTES", d.max_image_bytes),
                   max_image_px=num("MAX_IMAGE_PX", d.max_image_px),
                   max_body_bytes=num("MAX_BODY_BYTES", d.max_body_bytes),
                   cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
                   database_url=text("DATABASE_URL", d.database_url),
                   database_url_ro=text("DATABASE_URL_RO", d.database_url_ro),
                   db_pool_size=num("DB_POOL_SIZE", d.db_pool_size),
                   db_connect_timeout_s=num("DB_CONNECT_TIMEOUT_S", d.db_connect_timeout_s),
                   minio_endpoint=text("MINIO_ENDPOINT", d.minio_endpoint),
                   minio_access_key=text("MINIO_ACCESS_KEY", d.minio_access_key),
                   minio_secret_key=text("MINIO_SECRET_KEY", d.minio_secret_key),
                   minio_bucket=text("MINIO_BUCKET", d.minio_bucket),
                   minio_secure=text("MINIO_SECURE", "").lower() in ("1", "true", "yes"),
                   max_photo_bytes=num("MAX_PHOTO_BYTES", d.max_photo_bytes),
                   max_pages_per_exam=num("MAX_PAGES_PER_EXAM", d.max_pages_per_exam),
                   max_read_batch=num("MAX_READ_BATCH", d.max_read_batch),
                   trash_retention_days=num("TRASH_RETENTION_DAYS", d.trash_retention_days),
                   daily_read_limit=num("DAILY_READ_LIMIT", d.daily_read_limit),
                   default_owner_id=text("DEFAULT_OWNER_ID", d.default_owner_id),
                   llm_api_key=text("LLM_API_KEY", d.llm_api_key),
                   segment_model=text("SEGMENT_MODEL", d.segment_model),
                   read_model=text("READ_MODEL", d.read_model),
                   reread_model=text("REREAD_MODEL", d.reread_model),
                   llm_timeout_s=num("LLM_TIMEOUT_S", d.llm_timeout_s),
                   recognition_engine=text("RECOGNITION_ENGINE", d.recognition_engine).strip().lower(),
                   segment_image_long_side=num("SEGMENT_IMAGE_LONG_SIDE", d.segment_image_long_side))
