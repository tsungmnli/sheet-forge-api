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
    page_number: bool = False   # 쪽 번호(아래 가운데)
    page_number_style: str = "dash"   # dash: "- 1 -" | total: "1 / 5" | box: 상자 안 "1 / 5"
    header_mark_position: str = "right"   # left | right | outside
    header_need: int = 0      # 머리 표식에 필요한 머리말 높이. 표식이 없어도 값을 준다(웹이 미리 알려 줄 수 있게)
    footer_need: int = 0      # 쪽 번호에 필요한 꼬리말 높이. 쪽 번호가 없으면 0
    header_raised_from: int | None = None   # 안전장치로 머리말 여백을 올렸으면 원래 값
    footer_raised_from: int | None = None   # 안전장치로 꼬리말 여백을 올렸으면 원래 값

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
                "eq_hwp": self.eq_font_hwp,
                # 배치 미리보기·여백 경고용. 여백은 안전장치까지 적용된 실제 값이다
                "paper_w_mm": mm(self.page_horizontal),
                "paper_h_mm": mm(self.page_w if self.landscape else self.page_h),
                "margins_mm": {k: mm(getattr(self, k)) for k in ("top", "header", "bottom", "footer", "left", "right")},
                "header_need_mm": mm(self.header_need), "footer_need_mm": mm(self.footer_need),
                "header_raised_from_mm": None if self.header_raised_from is None else mm(self.header_raised_from),
                "footer_raised_from_mm": None if self.footer_raised_from is None else mm(self.footer_raised_from)}


def plan_layout(preset: ExportPreset) -> LayoutContext:
    # section이 layout을 가져다 쓰므로 순환을 피해 여기서 가져온다
    from .section import footer_need_h, header_mark_need_h

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
    font_hwp = round(preset.typography.font_size_pt * 100)
    header, footer = mm_to_hwp(m.header), mm_to_hwp(m.footer)
    header_need = header_mark_need_h()
    footer_need = footer_need_h(preset.page_number.enabled, preset.page_number.style, font_hwp,
                                preset.typography.line_spacing_pct)
    # 마지막 안전장치: 표식·쪽 번호가 여백보다 크면 한글에서 본문과 겹친다. 화면은 값을 바꾸지 않고 제안만 하므로
    # 여기서 필요한 만큼만 올린다. 쪽 설정과 쪽 높이 추정(FIGURE_TALL)이 같은 값을 쓰도록 이곳 한 군데서만 올린다
    header_from = footer_from = None
    if preset.header_mark.text.strip() and header < header_need:
        header_from, header = header, header_need
    if footer_need and footer < footer_need:
        footer_from, footer = footer, footer_need
    return LayoutContext(
        page_w=pw, page_h=ph, landscape=landscape,
        top=mm_to_hwp(m.top), header=header, bottom=mm_to_hwp(m.bottom),
        footer=footer, left=left, right=right, gutter=gutter,
        col_count=n, col_gap=gap, page_horizontal=horizontal, body_w=body, col_w=col,
        font_hwp=font_hwp,
        eq_hwp=round(preset.typography.equation_size_pt * 100),
        line_spacing_pct=preset.typography.line_spacing_pct, align=align,
        col_divider=preset.columns.divider and n >= 2, page_number=preset.page_number.enabled,
        page_number_style=preset.page_number.style, header_mark_position=preset.header_mark.position,
        header_need=header_need, footer_need=footer_need, header_raised_from=header_from, footer_raised_from=footer_from)
