"""요청 모델 (설계 4장). 문항은 라이브러리가 읽는 필드만 구조를 검사하고, 나머지 필드는 그대로 통과시킨다."""
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_serializer

from .preset_shape import PresetValue


class _Loose(BaseModel):
    model_config = ConfigDict(extra="allow")


class InlineIn(_Loose):
    t: str
    v: str | None = None
    latex: str | None = None
    breaks: list[int] | None = None


class BoxLineIn(_Loose):
    inlines: list[InlineIn] = Field(default_factory=list)


class StemBlockIn(_Loose):
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


class ChoicesIn(_Loose):
    items: list[list[InlineIn]] = Field(default_factory=list)
    layout: str = "auto"


class ContentIn(_Loose):
    stem: list[StemBlockIn] = Field(default_factory=list)
    choices: ChoicesIn | None = None
    figures: list[dict[str, Any]] = Field(default_factory=list)


class ProblemIn(_Loose):
    id: str
    status: str = ""
    content: ContentIn


class ExportRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field("", max_length=200)
    preset: PresetValue | None = None
    problems: list[ProblemIn] = Field(default_factory=list)
    images: dict[str, str] = Field(default_factory=dict)   # ref → base64 PNG


class LayoutPreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preset: PresetValue | None = None
