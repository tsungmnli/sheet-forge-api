"""웹 REST API 요청·응답 모델 (OpenAPI 스펙의 근거, 설계 5장).

poll_after_ms는 처리 중인 것이 있을 때만 값이 있고, 없으면 null이다(웹은 null이면 폴링을 멈춘다).
"""
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_serializer


class ExamCreateIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    title: str = Field("", max_length=200)
    student: str = Field("", max_length=100)
    memo: str = Field("", max_length=2000)


class ExamPatchIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    title: str | None = Field(None, max_length=200)
    student: str | None = Field(None, max_length=100)
    memo: str | None = Field(None, max_length=2000)


class PageOrderIn(BaseModel):
    page_ids: list[str] = Field(max_length=100)


class ProcessingOut(BaseModel):
    state: str  # queued | running | done | failed
    step: str | None = None  # correcting | segmenting
    message: str | None = None


class ExamOut(BaseModel):
    id: str
    title: str
    student: str
    memo: str
    version: int
    created_at: str
    updated_at: str
    page_count: int
    picked_count: int
    needs_review: int
    confirmed: int
    next_action: str  # upload | pick | read | review | worksheet
    poll_after_ms: int | None = None


class ExamListOut(BaseModel):
    items: list[ExamOut]
    next_cursor: str | None = None


class PageOut(BaseModel):
    id: str
    exam_id: str
    order: int
    thumb_url: str
    processing: ProcessingOut
    picked_count: int
    version: int


class PageListOut(BaseModel):
    items: list[PageOut]
    poll_after_ms: int | None = None


class SegmentOut(BaseModel):
    id: str
    bbox: list[float]
    number: str | None = None
    marked: bool


class ImageOut(BaseModel):
    original_url: str | None = None
    corrected_url: str | None = None
    width: int | None = None
    height: int | None = None


class PageDetailOut(PageOut):
    image: ImageOut
    correction: dict | None = None
    segments: list[SegmentOut]
    poll_after_ms: int | None = None


# ---- B2: 문제 칸·문제 요청 (웹 REST API 설계 5.3~5.5) ----
class SegmentPatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    marked: bool


class SegmentsMarkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    marked: bool
    segment_ids: list[str] | None = Field(None, max_length=500)
    page_id: str | None = None


class SegmentItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str | None = None
    bbox: list[float] = Field(min_length=4, max_length=4)
    number: str | None = Field(None, max_length=20)


class SegmentsPutIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segments: list[SegmentItemIn] = Field(max_length=100)


class ReadIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segment_ids: list[str] | None = Field(None, max_length=500)  # 50 초과는 서비스가 TOO_MANY_SEGMENTS로 거절


# ---- PUT /problems/{id}/content 요청 모델 (README 6.3·6.4). 응답 ContentOut과 짝이다 ----
# 모르는 키는 통과시킨다(웹이 받은 값을 그대로 돌려 보내도 되게). 값 길이·그림 참조 검사는 problem_logic이 한다.
class _OpenIn(BaseModel):
    model_config = ConfigDict(extra="allow")


class TextInlineIn(_OpenIn):
    t: Literal["text"]
    v: str = ""
    bold: bool | None = None
    underline: bool | None = None
    conf: float | None = None


class MathInlineIn(_OpenIn):
    t: Literal["math"]
    latex: str = ""
    breaks: list[int] | None = None
    conf: float | None = None


class ImageInlineIn(_OpenIn):
    t: Literal["image"]
    ref: str | None = None
    conf: float | None = None


InlineIn = Annotated[Union[TextInlineIn, MathInlineIn, ImageInlineIn], Field(discriminator="t")]


class BoxLineIn(_OpenIn):
    inlines: list[InlineIn] = Field(default_factory=list)


class StemBlockIn(_OpenIn):
    """type: paragraph(inlines) · box(title, paragraphs) · table(rows: 행 → 칸 → 조각 목록)."""
    type: str = "paragraph"
    inlines: list[InlineIn] = Field(default_factory=list)
    title: str | None = None
    paragraphs: list[BoxLineIn] | None = None
    rows: list[list[list[InlineIn]]] | None = None

    @model_serializer(mode="wrap")
    def _tidy(self, handler):
        d = handler(self)
        for k in ("title", "paragraphs", "rows"):
            if d.get(k) is None:
                d.pop(k, None)
        if d.get("type") in ("box", "table") and not d.get("inlines"):
            d.pop("inlines", None)
        return d


class ChoicesIn(_OpenIn):
    items: list[list[InlineIn]] = Field(default_factory=list)
    layout: str = "auto"


class FigureEditIn(_OpenIn):
    """그림은 서버가 만든 것만 있다. 요청에서는 use·placement·width_mm만 바뀐다(나머지는 받은 값 그대로 돌려 보내도 된다)."""
    id: str | None = None
    raw_ref: str | None = None
    clean_ref: str | None = None
    use: Literal["raw", "clean"] | None = None
    placement: Literal["after_stem", "after_choices"] | None = None
    width_mm: float | None = None


class ContentPutBody(_OpenIn):
    stem: list[StemBlockIn] = Field(default_factory=list)
    choices: ChoicesIn | None = None
    figures: list[FigureEditIn] = Field(default_factory=list)


class ContentPutIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: ContentPutBody
    points: float | None = Field(None, ge=0, le=1000)


class FigureAddIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bbox: list[float] = Field(min_length=4, max_length=4)
    placement: Literal["after_stem", "after_choices"] = "after_stem"
    width_mm: float = Field(60, ge=5, le=400)


class FigureCleanLevelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    level: int = Field(ge=0, le=4)   # 0 = 원본, 1~4 = 정리 세기


class FigureRegionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bbox: list[float] = Field(min_length=4, max_length=4)
