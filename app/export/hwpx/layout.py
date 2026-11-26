"""LayoutContext: preset에서 파생되는 폭·크기 (설계 5.3). 코드에 42520 같은 값을 쓰지 않는다."""
from dataclasses import dataclass

from .errors import PresetError
from .preset import ExportPreset, paper_hwp, mm_to_hwp, column_gap_hwp, validate_preset


@dataclass(frozen=True)
class LayoutContext:
    page_w: int            # pagePr width (세로 기준)
    page_h: int            # pagePr height (세로 기준)
    landscape: bool
    top: int
    header: int
    bottom: int
    footer: int
    left: int
    right: int
    gutter: int
    col_count: int
    col_gap: int
    page_horizontal: int   # 쪽 가로 길이
    body_w: int
    col_w: int
    font_hwp: int          # 글자 크기 HWPUNIT = pt × 100 (= 수식 baseUnit)
    line_spacing_pct: int
    align: str             # JUSTIFY | LEFT
    eq_hwp: int = 0        # 수식 크기 HWPUNIT = pt × 100 (= 수식 baseUnit). 0이면 글자 크기를 따른다
    col_divider: bool = False   # 단 구분선(2단 이상일 때만 True)
    page_number: bool = False   # 쪽 번호(아래 가운데, "- 1 -")

    @property
    def eq_font_hwp(self) -> int:
        return self.eq_hwp or self.font_hwp

    @property
    def landscape_attr(self) -> str:
        return "NARROWLY" if self.landscape else "WIDELY"  # [검증 t18]

    def summary(self) -> dict:
        mm = lambda v: round(v * 25.4 / 7200, 2)
        return {"body_w": self.body_w, "col_w": self.col_w, "body_w_mm": mm(self.body_w),
                "col_w_mm": mm(self.col_w), "col_gap": self.col_gap, "font_hwp": self.font_hwp,
                "eq_hwp": self.eq_font_hwp}


def plan_layout(preset: ExportPreset) -> LayoutContext:
    errors = validate_preset(preset)
    if errors:
        raise PresetError(errors)
    pw, ph = paper_hwp(preset.paper)  # 세로 기준
    landscape = preset.orientation == "landscape"
    m = preset.margins_mm
    left, right, gutter = mm_to_hwp(m.left), mm_to_hwp(m.right), mm_to_hwp(m.gutter)
    horizontal = ph if landscape else pw  # [검증 4.9] 가로일 때 긴 변
    body = horizontal - left - right - gutter
    n = preset.columns.count
    gap = column_gap_hwp(preset)
    col = (body - gap * (n - 1)) // n
    a = preset.typography.align
    align = "JUSTIFY" if (a == "justify" or (a == "auto" and n == 1)) else "LEFT"  # [검증 4.6]
    return LayoutContext(
        page_w=pw, page_h=ph, landscape=landscape,
        top=mm_to_hwp(m.top), header=mm_to_hwp(m.header), bottom=mm_to_hwp(m.bottom),
        footer=mm_to_hwp(m.footer), left=left, right=right, gutter=gutter,
        col_count=n, col_gap=gap, page_horizontal=horizontal, body_w=body, col_w=col,
        font_hwp=round(preset.typography.font_size_pt * 100),
        eq_hwp=round(preset.typography.equation_size_pt * 100),
        line_spacing_pct=preset.typography.line_spacing_pct, align=align,
        col_divider=preset.columns.divider and n >= 2, page_number=preset.page_number.enabled)
