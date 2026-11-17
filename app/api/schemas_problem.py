"""문제 확인 화면 응답 모델 (웹 REST API 설계 5.4~5.5). OpenAPI 스펙에 응답 모양을 넣기 위한 것이다.

problem_view()가 만드는 dict와 키가 같다. content는 ContentOut으로 선언한다(README 6.3·6.4). 모르는 키는 그대로 통과시킨다.
"""
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

ProblemStatus = Literal["recognizing", "needs_review", "confirmed", "failed"]


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[Any] = []
    retryable: bool = False
    request_id: str | None = None


class ErrorOut(BaseModel):
    error: ErrorBody


# ---- 문제 내용(content) 응답 모델 (README 6.3·6.4) ----
class _OpenOut(BaseModel):
    """저장된 값에 모르는 키가 있어도 응답이 깨지지 않게 통과시킨다."""
    model_config = ConfigDict(extra="allow")


class TextInlineOut(_OpenOut):
    t: Literal["text"]
    v: str = ""
    bold: bool | None = None
    underline: bool | None = None
    conf: float | None = None


class MathInlineOut(_OpenOut):
    t: Literal["math"]
    latex: str = ""
    breaks: list[int] | None = None
    conf: float | None = None


class ImageInlineOut(_OpenOut):
    t: Literal["image"]
    ref: str | None = None
    conf: float | None = None


InlineOut = Annotated[Union[TextInlineOut, MathInlineOut, ImageInlineOut], Field(discriminator="t")]


class StemBlockOut(_OpenOut):
    type: str = "paragraph"
    inlines: list[InlineOut] = []


class ChoicesOut(_OpenOut):
    items: list[list[InlineOut]] = []
    layout: str = "auto"


class FigureOut(_OpenOut):
    id: str
    kind: str = "crop"                       # crop(지금) · scene(후속)
    raw_ref: str | None = None
    clean_ref: str | None = None
    levels: dict[str, str | None] | None = None   # 정리 세기별 미리보기(1~4) → 이미지 ref
    clean_level: int | None = None                # 고른 세기(0 = 원본)
    erased: bool = False                          # 낙서 지우개로 고친 그림이면 True(clean_ref가 지운 결과)
    use: Literal["raw", "clean"] = "clean"
    placement: Literal["after_stem", "after_choices"] = "after_stem"
    width_mm: float | None = None
    bbox: list[float] | None = None


class RemovedFigureOut(FigureOut):
    removed_at: str | None = None            # 지운 시각(ISO). 되살리기 목록 표시용


class ContentOut(_OpenOut):
    stem: list[StemBlockOut] = []
    choices: ChoicesOut = ChoicesOut()
    figures: list[FigureOut] = []


class ProblemSourceOut(BaseModel):
    page_id: str
    segment_id: str
    bbox: list[float]
    number: str | None = None
    crop_url: str | None = None


class OcrOut(BaseModel):
    has_recognized: bool


class HintOut(BaseModel):
    path: str
    kind: Literal["low_confidence", "math_warning"]
    message: str | None = None


class BlockerOut(BaseModel):
    path: str
    code: str
    message: str


class ChecksOut(BaseModel):
    can_confirm: bool
    blockers: list[BlockerOut]


class ProblemOut(BaseModel):
    id: str
    exam_id: str
    status: ProblemStatus
    version: int
    source: ProblemSourceOut
    content: ContentOut
    points: float | None = None
    ocr: OcrOut
    hints: list[HintOut]
    removed_figures: list[RemovedFigureOut] = []   # 지웠지만 되살릴 수 있는 그림
    checks: ChecksOut
    poll_after_ms: int | None = None


class NeighborsOut(BaseModel):
    index: int
    total: int
    prev_id: str | None = None
    next_id: str | None = None


# 라우터 데코레이터용 공통 문서
ETAG_HEADER = {"ETag": {"description": "현재 version. 다음 수정 때 If-Match로 되돌려 보낸다.",
                        "schema": {"type": "string"}}}


def _err(desc: str) -> dict:
    return {"model": ErrorOut, "description": desc}


ERR_COMMON = {404: _err("없거나 남의 것 (NOT_FOUND)")}
ERR_WRITE = {**ERR_COMMON,
             409: _err("지금 상태에서는 할 수 없음 (PROBLEM_CONFIRMED, PROBLEM_BUSY, MATH_UNSUPPORTED)"),
             422: _err("요청 형식 오류 (REQUEST_INVALID, FIGURE_REF_INVALID, EMPTY_PROBLEM)")}
ERR_LOCKED = {**ERR_WRITE,
              412: _err("version이 낡음 (VERSION_CONFLICT)"),
              428: _err("If-Match 헤더 없음 (VERSION_REQUIRED)")}


def ok(code: int = 200) -> dict:
    """응답 헤더(ETag)를 스펙에 선언한다."""
    return {code: {"description": "문제 전체", "headers": ETAG_HEADER}}


# ---- 시험지 문제 탭 · 읽기 요청 · 한꺼번에 고르기 (설계 5.3~5.4) ----
ListState = Literal["not_read", "recognizing", "needs_review", "confirmed", "failed"]


class ProblemListItemOut(BaseModel):
    """시험지 '문제' 탭의 한 항목. 고른 칸 기준이라 읽기 전 칸도 not_read로 나온다."""
    segment_id: str
    page_id: str
    number: str | None = None
    bbox: list[float]
    crop_url: str | None = None
    state: ListState
    problem_id: str | None = None
    preview: str
    preview_tex: str = ""
    badges: list[str]


class ProblemListOut(BaseModel):
    items: list[ProblemListItemOut]
    poll_after_ms: int | None = None


class ReadSkippedOut(BaseModel):
    segment_id: str
    reason: Literal["not_found", "already_read", "not_picked"]


class ReadCreatedOut(BaseModel):
    id: str
    segment_id: str
    status: Literal["recognizing"]


class ReadOut(BaseModel):
    requested: int
    skipped: list[ReadSkippedOut]
    problems: list[ReadCreatedOut]
    poll_after_ms: int | None = None


class MarkOut(BaseModel):
    changed: int
    skipped: int
    picked_count: int


ERR_READ = {**ERR_COMMON,
            422: _err("요청 형식 오류 (REQUEST_INVALID, TOO_MANY_SEGMENTS)"),
            429: _err("하루 읽기 한도 (READ_LIMIT)")}
ERR_MARK = {**ERR_COMMON, 422: _err("칸 목록과 사진을 함께 지정함 (REQUEST_INVALID)")}
