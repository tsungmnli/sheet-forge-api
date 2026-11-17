"""홈·학생·휴지통·설정 응답 모델 (웹 REST API 설계 5.1·5.9). OpenAPI 스펙에 응답 모양을 넣기 위한 것이다."""
from typing import Literal

from pydantic import BaseModel


# ---- 홈, 학생 ----
class NextProblemOut(BaseModel):
    exam_id: str
    problem_id: str


class TodoOut(BaseModel):
    needs_review: int
    recognizing: int
    failed: int
    next_problem: NextProblemOut | None = None  # 확인할 문제가 없으면 null


class HomeOut(BaseModel):
    todo: TodoOut


class StudentsOut(BaseModel):
    items: list[str]


# ---- 휴지통 ----
class TrashItemOut(BaseModel):
    type: Literal["exam", "page", "problem", "worksheet"]
    id: str
    label: str
    deleted_at: str
    purge_at: str  # 보관 기간이 끝나 영구 삭제되는 시각


class TrashListOut(BaseModel):
    items: list[TrashItemOut]


class RestoreOut(BaseModel):
    type: str
    id: str
    restored: dict[str, int]  # 종류별로 되살린 개수 (같이 지운 것 포함)


# ---- 내 정보, 설정 ----
class MeOut(BaseModel):
    id: str
    display_name: str
    email: str | None = None   # 로그인을 켠 경우에만 채운다


class SettingsOut(BaseModel):
    font_scale: Literal[100, 115, 130, 150]
    student_name_display: Literal["full", "alias", "masked"]
    original_photo_retention_days: Literal[0, 7, 30, 90]  # 0 = 계속 보관
    default_preset_id: str | None = None
    auto_next_after_confirm: bool
