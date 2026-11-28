"""웹 REST API 테이블 (설계 11장). B1: exams, pages, segments, jobs."""
from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CommonColumns


class Exam(CommonColumns, Base):
    __tablename__ = "exams"
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    student: Mapped[str] = mapped_column(String(100), nullable=False, default="", server_default="")
    memo: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    # 출처: 내보낼 때 "[대안중 2025기말]"처럼 찍는 인쇄용 이름(관리용 제목과 별개). 비면 찍지 않는다
    source_label: Mapped[str] = mapped_column(String(100), nullable=False, default="", server_default="")
    __table_args__ = (Index("ix_exams_owner_updated", "owner_id", "updated_at"),)


class Page(CommonColumns, Base):
    __tablename__ = "pages"
    exam_id: Mapped[str] = mapped_column(String(40), ForeignKey("exams.id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    original_ref: Mapped[str | None] = mapped_column(String(40), nullable=True)  # 보존 기간 뒤 null
    corrected_ref: Mapped[str | None] = mapped_column(String(40), nullable=True)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    correction: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # {mode, rotation, corners, applied}. null = 자동(예전 사진)
    processing: Mapped[dict] = mapped_column(JSONB, nullable=False)       # {state, step, message}
    __table_args__ = (Index("ix_pages_exam_position", "exam_id", "position"),
                      Index("ix_pages_original_ref", "original_ref"),
                      Index("ix_pages_corrected_ref", "corrected_ref"))


class Segment(CommonColumns, Base):
    __tablename__ = "segments"
    page_id: Mapped[str] = mapped_column(String(40), ForeignKey("pages.id"), nullable=False)
    exam_id: Mapped[str] = mapped_column(String(40), ForeignKey("exams.id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)           # 읽는 순서
    bbox: Mapped[list] = mapped_column(JSONB, nullable=False)                # [x0, y0, x1, y1], 보정본 기준 0~1
    number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    marked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    __table_args__ = (Index("ix_segments_page_position", "page_id", "position"),
                      Index("ix_segments_exam_marked", "exam_id", "marked"))


class Job(Base):
    """내부 작업 큐(웹에 노출하지 않음, 설계 6장)."""
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_id: Mapped[str] = mapped_column(String(40), nullable=False)
    state: Mapped[str] = mapped_column(String(12), nullable=False, default="queued", server_default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        # 같은 대상의 같은 작업은 진행 중에 하나만(중복 클릭 방지)
        Index("uq_jobs_active_target", "kind", "target_id", unique=True,
              postgresql_where=text("state IN ('queued','running')")),
        Index("ix_jobs_state_run_after", "state", "run_after"),
    )


class Problem(CommonColumns, Base):
    __tablename__ = "problems"
    exam_id: Mapped[str] = mapped_column(String(40), ForeignKey("exams.id"), nullable=False)
    segment_id: Mapped[str] = mapped_column(String(40), ForeignKey("segments.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="recognizing", server_default="recognizing")
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)              # README 6.3 (stem / choices / figures)
    points: Mapped[float | None] = mapped_column(Float, nullable=True)
    recognized: Mapped[dict | None] = mapped_column(JSONB, nullable=True)     # 처음 읽은 결과(되돌리기용, 응답에 싣지 않음)
    ocr_meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    crop_ref: Mapped[str | None] = mapped_column(String(40), nullable=True)
    search_text: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    __table_args__ = (
        Index("uq_problems_segment_alive", "segment_id", unique=True, postgresql_where=text("deleted_at IS NULL")),
        Index("ix_problems_exam_status", "exam_id", "status"),
        Index("ix_problems_crop_ref", "crop_ref"))


class ReadUsage(Base):
    __tablename__ = "read_usage"
    owner_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    units: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class Worksheet(CommonColumns, Base):
    """문제지(REST 5.7). 파일은 저장하지 않고 last_export만 기록한다."""
    __tablename__ = "worksheets"
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    subtitle: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")   # 첫 쪽 제목 상자의 부제
    student: Mapped[str] = mapped_column(String(100), nullable=False, default="", server_default="")
    preset: Mapped[dict] = mapped_column(JSONB, nullable=False)    # 선택한 시점의 값 복사(REST 5.8)
    unconfirmed_policy: Mapped[str] = mapped_column(String(8), nullable=False, default="skip", server_default="skip")
    last_export: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    __table_args__ = (Index("ix_worksheets_owner_updated", "owner_id", "updated_at"),)


class WorksheetItem(Base):
    """문제지에 담긴 문제와 순서. 같은 문제는 한 문제지에 한 번만."""
    __tablename__ = "worksheet_items"
    worksheet_id: Mapped[str] = mapped_column(String(40), ForeignKey("worksheets.id"), primary_key=True)
    problem_id: Mapped[str] = mapped_column(String(40), ForeignKey("problems.id"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (Index("ix_worksheet_items_pos", "worksheet_id", "position"),
                      Index("ix_worksheet_items_problem", "problem_id"))


class ExportPresetRecord(CommonColumns, Base):
    """저장된 모양(내 모양). 내장 모양은 코드 상수라 저장하지 않는다."""
    __tablename__ = "export_presets"
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    preset: Mapped[dict] = mapped_column(JSONB, nullable=False)
    __table_args__ = (Index("ix_export_presets_owner", "owner_id"),)


class UserSettings(Base):
    """선생님별 설정(REST 5.9). 바꾼 값만 data에 두고, 읽을 때 기본값과 합친다."""
    __tablename__ = "user_settings"
    owner_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class UsageEvent(Base):
    """LLM 호출 한 번의 사용량(B5-3c). 내용은 저장하지 않는다. 한도 계산은 read_usage가 맡고, 이 표는 월 비용 확인용이다."""
    __tablename__ = "usage_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    job_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    target_id: Mapped[str] = mapped_column(String(40), nullable=False)
    call: Mapped[str] = mapped_column(String(10), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    thinking_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    __table_args__ = (Index("ix_usage_events_created_at", "created_at"),)


class User(Base):
    """로그인 계정. id는 owner_id와 같다. 첫 가입자는 기존 데이터를 이어받도록 default_owner_id를 id로 쓴다."""
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)  # 소문자로만 저장·비교
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AuthSession(Base):
    """로그인 세션. 브라우저는 무작위 토큰을, DB는 그 해시만 가진다. 쓸 때마다 만료가 늘어난다(하루 한 번만 기록)."""
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String(200), nullable=True)
    __table_args__ = (Index("ix_auth_sessions_user_id", "user_id"), Index("ix_auth_sessions_expires_at", "expires_at"))


class EmailToken(Base):
    """메일로 보내는 1회용 링크(초대 invite, 비밀번호 재설정 reset). 이메일 주소에 묶는다(초대 시점엔 계정이 아직 없다)."""
    __tablename__ = "email_tokens"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (Index("ix_email_tokens_email_purpose", "email", "purpose"),)
