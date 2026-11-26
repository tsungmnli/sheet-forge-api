"""칸 고르기·수식 점검·한글 파일 만들기 응답 모델 (웹 REST API 설계 5.3·5.6·5.7). OpenAPI 스펙용."""
from typing import Any, Literal

from pydantic import BaseModel

from .preset_shape import PresetValueOut

from .schemas_problem import ErrorOut
from .schemas_web import SegmentOut


# ---- 문제 칸 (5.3) ----
class SegmentPatchOut(BaseModel):
    """PATCH /pages/{pid}/segments/{sid}: 한 칸을 고르거나 해제한 결과."""
    segment: SegmentOut
    picked_count: int  # 이 사진에서 고른 개수
    exam_picked_count: int  # 이 시험지 전체에서 고른 개수


class SegmentsPutOut(BaseModel):
    segments: list[SegmentOut]
    picked_count: int


ERR_SEGMENT = {404: {"model": ErrorOut, "description": "없거나 남의 것 (NOT_FOUND)"},
               409: {"model": ErrorOut, "description": "읽은 문제가 있는 칸 (SEGMENT_HAS_PROBLEM)"}}
ERR_SEGMENTS_PUT = {**ERR_SEGMENT, 422: {"model": ErrorOut, "description": "요청 형식 오류 (REQUEST_INVALID)"}}
ERR_RECORRECT = {404: {"model": ErrorOut, "description": "없거나 남의 것 (NOT_FOUND)"},
                 409: {"model": ErrorOut, "description": "처리 중 (PAGE_BUSY) · 원본 만료 (ORIGINAL_EXPIRED) · "
                                                         "옮긴 문제 있음 (PAGE_HAS_PROBLEMS)"},
                 422: {"model": ErrorOut, "description": "모서리 값 오류 (REQUEST_INVALID)"}}


# ---- 수식 점검 (5.6) ----
class MathResultOut(BaseModel):
    status: Literal["ok", "warn", "unsupported"]
    message: str | None = None
    est_width: float | None = None  # 기준 글자 크기 대비 폭(em). unsupported면 null


class MathCheckOut(BaseModel):
    results: list[MathResultOut]


# ---- 한글 파일 만들기 (5.7) ----
class ExportLinkOut(BaseModel):
    exam_id: str
    problem_id: str


class ExportItemOut(BaseModel):
    code: str
    severity: Literal["info", "warn", "error"]
    message: str
    problem_id: str | None = None
    where: str | None = None
    link: ExportLinkOut | None = None  # 문제 확인 화면으로 가는 링크용


class ExportReportOut(BaseModel):
    status: Literal["ok", "warnings"]
    summary: str  # 한 줄 요약(쉬운 문장)
    items: list[ExportItemOut]
    stats: dict[str, Any]
    layout: dict[str, Any]
    effective_preset: PresetValueOut


class ExportFileOut(BaseModel):
    name: str
    size: int
    content_base64: str


class ExportOut(BaseModel):
    report: ExportReportOut
    file: ExportFileOut


HWPX_200 = {200: {"description": "format=json: 리포트와 base64 파일. format=hwpx: 파일 본문과 X-Export-* 헤더",
                  "content": {"application/vnd.hancom.hwpx": {"schema": {"type": "string", "format": "binary"}}},
                  "headers": {"X-Export-Status": {"schema": {"type": "string"}},
                              "X-Export-Warnings": {"schema": {"type": "integer"}},
                              "X-Export-Errors": {"schema": {"type": "integer"}}}}}
ERR_EXPORT = {404: {"model": ErrorOut, "description": "없거나 남의 것 (NOT_FOUND)"},
              409: {"model": ErrorOut, "description": "확인 안 끝난 문제 (NOT_CONFIRMED)"},
              422: {"model": ErrorOut, "description": "내보낼 문제 없음·잘못된 모양 (EMPTY_EXPORT, PRESET_INVALID, SOURCE_NUMBER_MISSING)"},
              503: {"model": ErrorOut, "description": "DB·저장소 연결 실패 (DEPENDENCY_UNAVAILABLE)"}}
