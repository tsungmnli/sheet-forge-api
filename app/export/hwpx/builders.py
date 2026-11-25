"""문항 → 문단 명세(ParagraphSpec) (설계 8장, S3). XML 없이 문단 구성 규칙을 테스트할 수 있게 분리."""
import re
from dataclasses import dataclass, field

from ..math.convert import convert
from .images import load_image
from .preset import mm_to_hwp
from .report import ExportReport
from . import box_geometry as bg

_BAD_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")

# 수식 한 줄의 추정 폭이 단 폭의 이 비율을 넘으면 `#`을 넣는다 [설계 10장, README 6.7: 90%]
EQ_WRAP_RATIO = 0.9


@dataclass(frozen=True)
class Equation:
    """문단 안의 수식 조각. script는 한글 수식 스크립트(XML 이스케이프 전)."""
    script: str
    wrapped: bool = False   # 줄바꿈 `#`이 들어갔는가(cases의 `#`은 해당 없음)
    width_em: float = 0.0   # 추정 폭(em) — 선택지 열 수 결정에 쓴다


@dataclass
class Picture:
    """문단 안의 그림 조각(hp:pic). width·height는 표시 크기(HWPUNIT). bin_id는 내보낼 때 문서 순서로 부여.
    org_w·org_h는 이미지 원본 크기(픽셀 × PX_HWP). 한글이 imgClip을 이 크기 기준으로 해석하므로 필요하다.
    0이면 표시 크기를 쓴다."""
    png: bytes
    width: int
    height: int
    bin_id: int = 0
    org_w: int = 0
    org_h: int = 0


@dataclass
class BoxPart:
    """상자. title이 있으면 <보기> 상자(묶음 개체: 본문 글상자 + 윗선에 걸친 제목 글상자),
    title이 ""이면 제목 없는 상자(글상자 하나 — 샘플 시험지.hwpx의 조건 상자). lines는 줄마다 str | Equation 목록.
    body_pr·title_pr는 내보낼 때 StyleRegistry가 정한 문단 모양 id(제목 없는 상자는 title_pr를 쓰지 않는다)."""
    title: str
    lines: list
    geom: object
    body_pr: int = 0
    title_pr: int = 0


@dataclass
class TablePart:
    """표. rows는 행마다 셀(str | Equation 목록)의 목록. col_w·row_h는 HWPUNIT. cell_pr·border_id는 내보낼 때 정한다."""
    rows: list
    col_w: list
    row_h: list
    cell_pr: int = 0
    border_id: int = 0

    @property
    def width(self) -> int:
        return sum(self.col_w)

    @property
    def height(self) -> int:
        return sum(self.row_h)


class Tab:
    """선택지 사이의 탭. 폭은 한글이 다시 계산하므로 width=0으로 방출한다 [검증 4.7.1]."""
    __slots__ = ()


TAB = Tab()


@dataclass
class ParagraphSpec:
    parts: list = field(default_factory=list)  # str | Equation, 순서대로
    keep_with_next: bool = False
    keep_lines: bool = False
    role: str = "body"  # number | body | choice | blank
    problem_id: str | None = None
    tab_cols: int = 0   # 선택지 행의 열 수(탭 정지 계산용). 0이면 해당 없음

    @property
    def text(self) -> str:
        """글자 조각만 이은 문자열(수식은 제외). 테스트·디버깅용."""
        return "".join(p for p in self.parts if isinstance(p, str))


def clean_text(s: str) -> str:
    s = _BAD_XML.sub("", s)
    return s.replace("\t", " ").replace("\r\n", " ").replace("\n", " ").replace("\r", " ")


def _max_eq_em(layout) -> float:
    """한 줄에 허용할 수식 폭(em). em = 수식 baseUnit = 본문 글자 크기(HWPUNIT) [검증 t17a]."""
    return float("inf") if layout is None else EQ_WRAP_RATIO * layout.col_w / layout.font_hwp


def _math_part(il: dict, pid, where: str, report: ExportReport, max_em: float):
    """math inline → Equation 또는 폴백 텍스트(str). 변환 실패는 예외가 아니라 보고로 알린다(설계 10장)."""
    latex = clean_text(str(il.get("latex", "")))
    res = convert(latex, max_width_em=max_em, breaks=il.get("breaks"))
    if not res.ok:
        pos = "" if res.error_pos is None else f" (위치 {res.error_pos})"
        report.add("UNSUPPORTED_MATH", "warn", f"수식 변환 실패: {res.error}{pos} — 원본 LaTeX를 글자로 넣음", pid, where)
        return f"[수식 오류: {latex}]"
    for w in res.warnings:
        report.add("MATH_NOTE", "info", w, pid, where)
    if res.auto_broken:
        report.add("EQ_AUTO_BROKEN", "info", f"수식이 길어 `#` 줄바꿈 {len(res.breaks)}곳을 자동 삽입함", pid, where)
    if res.too_wide:
        report.add("EQ_TOO_WIDE", "warn",
                   f"수식 한 줄의 추정 폭({max(res.line_widths_em):.1f}em)이 단 폭의 {int(EQ_WRAP_RATIO * 100)}%를 넘는데 "
                   "더 쪼갤 곳이 없음", pid, where)
    return Equation(_BAD_XML.sub("", res.script), bool(res.breaks),
                    max(res.line_widths_em) if res.line_widths_em else res.est_width_em)


def _paragraph_parts(inlines: list, pid, report: ExportReport, max_em: float, path: str = "stem") -> list:
    out: list = []

    def add(x):
        if isinstance(x, str) and out and isinstance(out[-1], str):
            out[-1] += x
        elif x != "":
            out.append(x)

    for i, il in enumerate(inlines or []):
        t = il.get("t")
        where = f"{path}.inline[{i}]"
        if t == "text":
            if any(il.get(k) for k in ("bold", "underline", "fmt", "format")):
                report.add("TEXT_FORMAT_IGNORED", "info", "굵게·밑줄 서식을 무시함", pid, where)
            add(clean_text(str(il.get("v", ""))))
        elif t == "math":
            add(_math_part(il, pid, where, report, max_em))
        else:
            report.add("NOT_IMPLEMENTED", "warn", f"inline 종류 '{t}'는 아직 지원하지 않아 제외함", pid, where)
    return out


# ---------------------------------------------------------------- 선택지 [설계 9장, 검증 4.7.1]
# 글자 폭 계수(em) [제안]: 한글·기타 1.0, 영문·숫자 0.55(10pt 숫자 한 자리 552 관찰), 공백 0.4, 마커(①) 1.0.
CH_HANGUL, CH_ASCII, CH_SPACE, CH_MARKER = 1.0, 0.55, 0.4, 1.0
EQ_OUT_MARGIN = 112          # hp:outMargin left 56 + right 56
NEAR_LIMIT = 0.85            # 선택한 칸 폭의 85%를 넘으면 CHOICES_NEAR_LIMIT [설계 9장 6]


def marker(i: int) -> str:
    return chr(0x2460 + i)   # ① = U+2460 … ⑳


def _text_em(s: str) -> float:
    return sum(CH_SPACE if c == " " else CH_ASCII if c.isascii() else CH_HANGUL for c in s)


def item_width(parts: list, font_hwp: int) -> float:
    """선택지 하나의 추정 폭(HWPUNIT): 마커 + 공백 + 내용."""
    em = CH_MARKER + CH_SPACE
    extra = 0
    for p in parts:
        if isinstance(p, str):
            em += _text_em(p)
        elif isinstance(p, Equation):
            em += p.width_em
            extra += EQ_OUT_MARGIN
    return em * font_hwp + extra


def choose_cols(widths: list, col_w: float, safety: float) -> int:
    """5 → 3 → 2 → 1 순으로, 선택지 수 이하이고 max(폭)×(1+여유) ≤ 칸 폭인 첫 열 수 [설계 9장 2].
    선택지가 4개면 (4, 2, 1)을 쓴다(3+1 행이 되지 않게) [제안]."""
    cnt = len(widths)
    order = (4, 2, 1) if cnt == 4 else (5, 3, 2, 1)
    mx = max(widths)
    for n in order:
        if n <= cnt and mx * (1 + safety) <= col_w / n:
            return n
    return 1


def _choice_rows(items: list, pid, report: ExportReport, layout, safety: float) -> list:
    font = layout.font_hwp if layout else 1000
    col_w = layout.col_w if layout else float("inf")
    parsed = [_paragraph_parts(it, pid, report, float("inf"), f"choices[{k}]") for k, it in enumerate(items)]
    widths = [item_width(p, font) for p in parsed]
    n = choose_cols(widths, col_w, safety)
    if len(items) > 5:
        report.add("NOT_IMPLEMENTED", "warn", "⑥ 이상 마커는 한글에서 확인하지 않았지만 유니코드 ⑥~로 방출함", pid, "choices")
    cell = col_w / n
    if max(widths) > NEAR_LIMIT * cell:
        report.add("CHOICES_NEAR_LIMIT", "warn",
                   f"선택지 추정 폭({max(widths) / cell:.0%} of 칸 폭, {n}열)이 한계에 가까움 — 한글에서 줄이 갈라지면 직접 고치세요",
                   pid, "choices")
    rows = []
    for r0 in range(0, len(parsed), n):
        row: list = []
        for j, parts in enumerate(parsed[r0:r0 + n]):
            if j:
                row.append(TAB)
            first = marker(r0 + j) + " "
            if parts and isinstance(parts[0], str):
                row.append(first + parts[0])
                row.extend(parts[1:])
            else:
                row.append(first)
                row.extend(parts)
        rows.append(ParagraphSpec(row, role="choice", problem_id=pid, tab_cols=n))
    return rows


def build_problem_paragraphs(problem: dict, number_text: str, report: ExportReport, layout=None,
                             safety: float = 0.10, images=None, default_fig_mm=None):
    """번호 문단 + stem 문단들. keep은 문항 안에서의 위치로 정한다(마지막 문단만 keepWithNext=0) [검증 4.5].
    layout(LayoutContext)을 주면 단 폭에 맞춰 수식 `#` 줄바꿈을 결정한다. None이면 줄바꿈하지 않는다."""
    pid = problem.get("id")
    content = problem.get("content") or {}
    max_em = _max_eq_em(layout)
    # 그림 먼저 확인: 하나라도 못 찾으면 문항을 통째로 제외한다(None) [설계 13장 FIGURE_MISSING]
    figs = {"after_stem": [], "after_choices": []}
    missing = False
    for k, fig in enumerate(content.get("figures") or []):
        place = fig.get("placement") or "after_stem"
        if place not in figs:
            report.add("NOT_IMPLEMENTED", "warn", f"placement '{place}'는 아직 지원하지 않아 after_stem으로 처리함",
                       pid, f"figures[{k}]")
            place = "after_stem"
        pic = _figure_picture(fig, k, pid, report, layout, images, default_fig_mm)
        if pic is None:
            missing = True
        else:
            figs[place].append(pic)
    if missing:
        return None
    specs = [ParagraphSpec([number_text], role="number", problem_id=pid)]
    for bi, block in enumerate(content.get("stem") or []):
        if block.get("type") == "box":
            spec = _box_spec(block, bi, pid, report, layout)
            if spec is not None:
                specs.append(spec)
            continue
        if block.get("type") == "table":
            spec = _table_spec(block, bi, pid, report, layout)
            if spec is not None:
                specs.append(spec)
            continue
        if block.get("type", "paragraph") != "paragraph":
            report.add("NOT_IMPLEMENTED", "warn", f"블록 종류 '{block.get('type')}'는 아직 지원하지 않아 제외함", pid, "stem")
            continue
        specs.append(ParagraphSpec(_paragraph_parts(block.get("inlines"), pid, report, max_em, f"stem[{bi}]"),
                                   role="body", problem_id=pid))
    specs.extend(ParagraphSpec([p], role="figure", problem_id=pid) for p in figs["after_stem"])
    items = [it for it in (content.get("choices") or {}).get("items") or [] if it]
    if items:
        specs.extend(_choice_rows(items, pid, report, layout, safety))
    specs.extend(ParagraphSpec([p], role="figure", problem_id=pid) for p in figs["after_choices"])
    for s in specs[:-1]:
        s.keep_with_next, s.keep_lines = True, True
    specs[-1].keep_with_next, specs[-1].keep_lines = False, True
    return specs


# ---------------------------------------------------------------- 상자 [샘플 시험지.hwpx 기준]
def _box_spec(block: dict, bi: int, pid, report: ExportReport, layout):
    """box 블록({"type":"box","title":"<보기>" | "","paragraphs":[{"inlines":[...]} | [...], ...]}) → 상자 문단.
    title이 비어 있거나 없으면 제목 없는 상자(글상자 하나)로, 있으면 <보기> 상자(묶음 개체)로 만든다.
    상자 폭은 들어갈 단의 폭을 따르고(1·2·3단), 제목은 윗선 위 가로·세로 가운데에 놓는다.
    높이는 줄 수에서 추정한다(한글이 다시 계산하지 않는다)."""
    path = f"stem[{bi}]"
    col_w = layout.col_w if layout else bg.DEFAULT_COL_W
    font = layout.font_hwp if layout else 1000
    pct = layout.line_spacing_pct if layout else 160
    text_w = bg.box_width(col_w) - 2 * bg.TEXT_MARGIN
    max_em = EQ_WRAP_RATIO * text_w / font if layout else float("inf")
    lines, plan = [], []
    for k, para in enumerate(block.get("paragraphs") or []):
        inl = para.get("inlines") if isinstance(para, dict) else para
        parts = _paragraph_parts(inl, pid, report, max_em, f"{path}.paragraphs[{k}]")
        em = sum(bg.text_em(p) if isinstance(p, str) else p.width_em for p in parts)
        n_eq = sum(1 for p in parts if isinstance(p, Equation))
        lines.append(parts)
        plan.append((bg.line_rows(em, n_eq, text_w, font), n_eq > 0))
    if not lines:
        report.add("BOX_EMPTY", "warn", "내용이 없는 상자를 제외함", pid, path)
        return None
    title = clean_text(str(block.get("title") or "")).strip()   # 없으면 제목 없는 상자 (<보기>를 대신 붙이지 않는다)
    geom = bg.plan_box(col_w, title, plan, font, pct)
    report.add("BOX_HEIGHT_ESTIMATED", "info",
               f"상자 높이({geom.height})는 줄 수로 추정한 값 — 한글에서 글이 넘치거나 남으면 상자 크기를 조절하세요", pid, path)
    return ParagraphSpec([BoxPart(bg.display_title(title), lines, geom)], role="box", problem_id=pid)


# ---------------------------------------------------------------- 표 [샘플 시험지.hwpx 기준]
def _cell_inlines(cell):
    return cell.get("inlines") if isinstance(cell, dict) else cell


def _table_spec(block: dict, bi: int, pid, report: ExportReport, layout):
    """table 블록({"type":"table","rows":[[셀, ...], ...]}; 셀 = 인라인 목록 또는 {"inlines":[...]}) → 표 문단.
    표 폭은 단 폭에서 샘플만큼 줄이고, 열 폭은 내용 길이에 비례해 나눈다. 모든 셀은 가운데 정렬.
    행이 짧으면 빈 셀로 채운다. 셀 합치기·음영은 아직 지원하지 않는다."""
    path = f"stem[{bi}]"
    col_w = layout.col_w if layout else bg.DEFAULT_COL_W
    font = layout.font_hwp if layout else 1000
    pct = layout.line_spacing_pct if layout else 160
    raw = [r for r in (block.get("rows") or []) if r]
    ncols = max((len(r) for r in raw), default=0)
    if not raw or ncols == 0:
        report.add("TABLE_EMPTY", "warn", "내용이 없는 표를 제외함", pid, path)
        return None
    rows = []
    for ri, r in enumerate(raw):
        row = [_paragraph_parts(_cell_inlines(c), pid, report, float("inf"), f"{path}.rows[{ri}][{ci}]")
               for ci, c in enumerate(r)]
        rows.append(row + [[] for _ in range(ncols - len(row))])
    stats = [[(sum(bg.text_em(p) if isinstance(p, str) else p.width_em for p in cell),
               sum(1 for p in cell if isinstance(p, Equation)),
               any(isinstance(p, Equation) for p in cell)) for cell in row] for row in rows]
    weights = [max(s[j][0] for s in stats) + 2 * bg.CELL_MARGIN_X / font for j in range(ncols)]
    widths = bg.split_widths(weights, bg.table_width(col_w))
    heights = [bg.row_height(s, widths, font, pct) for s in stats]
    return ParagraphSpec([TablePart(rows, widths, heights)], role="table", problem_id=pid)


# ---------------------------------------------------------------- 그림 [설계 11장, 검증 4.7.2]
PX_HWP = 75   # 96dpi 가정 1px ≈ 75 HWPUNIT [검증 4.7]


def _width_hwp(v):
    try:
        mm = float(v)
    except (TypeError, ValueError):
        return None
    return mm_to_hwp(mm) if mm > 0 else None


def _figure_picture(fig: dict, k: int, pid, report: ExportReport, layout, images, default_mm):
    """figure → Picture. 못 찾으면 FIGURE_MISSING(error)을 보고하고 None."""
    where = f"figures[{k}]"
    ref = fig.get("raw_ref") if fig.get("use") == "raw" else fig.get("clean_ref")
    img, why = load_image(images, ref)
    if img is None:
        report.add("FIGURE_MISSING", "error", f"{why} — 문항을 제외함", pid, where)
        return None
    req = _width_hwp(fig.get("width_mm")) or _width_hwp(default_mm) or img.width_px * PX_HWP
    col_w = layout.col_w if layout else float("inf")
    w = min(req, col_w)
    if w < req:  # 단 폭을 넘는 그림은 한글이 줄여 주지 않으므로 비율 유지로 축소 [검증 4.7.2]
        report.add("FIGURE_SHRUNK", "info", f"그림 폭 {req}을 단 폭 {col_w}에 맞춰 줄임", pid, where)
    w = max(1, int(w))
    h = max(1, round(w * img.height_px / img.width_px))
    if layout:
        page_h = layout.page_w if layout.landscape else layout.page_h
        avail = page_h - layout.top - layout.bottom - layout.header - layout.footer
        if h > avail:
            report.add("FIGURE_TALL", "warn", f"그림 높이 {h}가 쪽에서 쓸 수 있는 높이 {avail}(추정)를 넘음", pid, where)
    return Picture(img.png, w, h, 0, img.width_px * PX_HWP, img.height_px * PX_HWP)


def blank_paragraph() -> ParagraphSpec:
    """문항 간 빈 문단은 문항 밖이라 keep 없음 [검증 4.5]."""
    return ParagraphSpec([], False, False, role="blank")
