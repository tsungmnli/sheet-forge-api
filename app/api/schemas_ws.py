"""문제지 요청·응답 모델 (웹 REST API 설계 5.7)."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .preset_shape import PresetValue, PresetValueOut


class WorksheetCreateIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    title: str = Field("", max_length=200)
    student: str | None = Field(None, max_length=100)
    from_exam_id: str | None = Field(None, max_length=40)
    problem_ids: list[str] | None = Field(None, max_length=1000)


class WorksheetPatchIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    title: str | None = Field(None, max_length=200)
    student: str | None = Field(None, max_length=100)
    preset: PresetValue | None = None
    preset_id: str | None = Field(None, max_length=60)
    unconfirmed_policy: Literal["skip", "fail"] | None = None


class ProblemIdsIn(BaseModel):
    problem_ids: list[str] = Field(max_length=1000)


class WsExamRef(BaseModel):
    id: str
    title: str


class WsItemOut(BaseModel):
    problem_id: str
    number: str | None
    status: str
    deleted: bool
    exam: WsExamRef
    preview: str
    crop_url: str | None


class WorksheetOut(BaseModel):
    id: str
    title: str
    student: str
    version: int
    items: list[WsItemOut]
    preset: PresetValueOut
    preset_id: str | None = None
    unconfirmed_policy: str
    layout: dict | None
    last_export: dict | None
    updated_at: str


class WorksheetListItem(BaseModel):
    id: str
    title: str
    student: str
    problem_count: int
    last_export: dict | None
    updated_at: str


class WorksheetListOut(BaseModel):
    items: list[WorksheetListItem]
    next_cursor: str | None
