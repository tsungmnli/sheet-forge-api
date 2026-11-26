"""ExportPreset 모델·검증·단위 변환 (설계 5.1, 5.2)."""
from dataclasses import dataclass, field, fields, is_dataclass, asdict

from .errors import PresetError


def mm_to_hwp(mm: float) -> int:
    """HWPUNIT = round(mm × 7200 / 25.4) [검증 README 4.9]."""
    return round(mm * 7200 / 25.4)


@dataclass
class Paper:
    kind: str = "A4"
    width_mm: float = 210.0   # 세로 기준 폭(작은 값)
    height_mm: float = 297.0  # 세로 기준 높이


@dataclass
class Margins:
    top: float = 5.0
    header: float = 10.0
    bottom: float = 5.0
    footer: float = 10.0
    left: float = 10.0
    right: float = 10.0
    gutter: float = 0.0


@dataclass
class Columns:
    count: int = 1
    gap_mm: float | None = None
    divider: bool = False   # 단 사이 세로 구분선(2단 이상일 때만 그려짐)


@dataclass
class Typography:
    font_name: str = "함초롬바탕"
    font_size_pt: float = 11.5   # 일반 글자
    equation_size_pt: float = 11.0   # 수식(baseUnit)
    line_spacing_pct: int = 160
    align: str = "auto"  # auto | left | justify


@dataclass
class Numbering:
    format: str = "{n:02d}"
    start: int = 1
    mode: str = "sequence"  # sequence: 담은 순서대로 새로 매김 | source: 시험지의 원래 번호 그대로


@dataclass
class PageNumber:
    enabled: bool = False   # 쪽 아래 가운데에 "- 1 -" 모양으로 넣음


@dataclass
class Spacing:
    between_problems: str = "blank_paragraph"
    blank_lines: int = 1   # 문제 사이 빈 줄 수(풀이 공간). 0~20


@dataclass
class Choices:
    layout: str = "auto"
    safety_ratio: float = 0.10


@dataclass
class Figures:
    default_width_mm: float | None = None


@dataclass
class Equation:
    size_mode: str = "auto"  # auto | estimated


@dataclass
class ExportPreset:
    paper: Paper = field(default_factory=Paper)
    orientation: str = "portrait"
    margins_mm: Margins = field(default_factory=Margins)
    columns: Columns = field(default_factory=Columns)
    typography: Typography = field(default_factory=Typography)
    numbering: Numbering = field(default_factory=Numbering)
    spacing: Spacing = field(default_factory=Spacing)
    choices: Choices = field(default_factory=Choices)
    figures: Figures = field(default_factory=Figures)
    equation: Equation = field(default_factory=Equation)
    page_number: PageNumber = field(default_factory=PageNumber)
    on_unconfirmed: str = "skip"  # skip | fail

    @classmethod
    def from_dict(cls, d: dict | None) -> "ExportPreset":
        errors: list = []
        obj = _build(cls, d or {}, "", errors)
        if errors:
            raise PresetError(errors)
        return obj

    def to_dict(self) -> dict:
        return asdict(self)

    def validate(self) -> None:
        errors = validate_preset(self)
        if errors:
            raise PresetError(errors)


def _build(cls, d, path, errors):
    if not isinstance(d, dict):
        errors.append(("PRESET_TYPE", f"{path or 'preset'}: 객체여야 함"))
        return cls()
    known = {f.name: f for f in fields(cls)}
    kwargs = {}
    for k, v in d.items():
        if k not in known:
            errors.append(("PRESET_UNKNOWN_KEY", f"{path}{k}: 알 수 없는 항목"))
            continue
        ftype = known[k].type
        if is_dataclass(ftype):
            kwargs[k] = _build(ftype, v, f"{path}{k}.", errors)
        else:
            kwargs[k] = v
    # 수식 크기가 없던 옛 모양은 그때처럼 글자 크기를 따라간다(기본값이 바뀌어도 이미 만든 문제지는 그대로)
    if cls is Typography and "font_size_pt" in kwargs and "equation_size_pt" not in kwargs:
        kwargs["equation_size_pt"] = kwargs["font_size_pt"]
    return cls(**kwargs)


# 한글이 쓰는 A4 용지 값(국배판 인식). 임의 크기는 round(mm→HWPUNIT).
_KNOWN_PAPER_HWP = {(210.0, 297.0): (59528, 84186)}


def paper_hwp(paper: Paper) -> tuple[int, int]:
    key = (float(paper.width_mm), float(paper.height_mm))
    if key in _KNOWN_PAPER_HWP:
        return _KNOWN_PAPER_HWP[key]
    return mm_to_hwp(paper.width_mm), mm_to_hwp(paper.height_mm)


def default_gap_hwp(count: int) -> int:
    """[검증 README 4.4] 1단 0, 2단 8mm(2268), 3단 4mm(1134)."""
    return {1: 0, 2: 2268, 3: 1134}[count]


def column_gap_hwp(p: ExportPreset) -> int:
    if p.columns.gap_mm is None:
        return default_gap_hwp(p.columns.count) if p.columns.count in (1, 2, 3) else 0
    return mm_to_hwp(p.columns.gap_mm)


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def validate_preset(p: ExportPreset) -> list:
    """오류 목록 [(코드, 메시지)]. 비어 있으면 유효."""
    e: list = []

    def err(code, msg):
        e.append((code, msg))

    # 타입
    paper_ok = _num(p.paper.width_mm) and _num(p.paper.height_mm) and p.paper.width_mm > 0 and p.paper.height_mm > 0
    if not paper_ok:
        err("PRESET_PAPER", "용지 폭·높이는 0보다 큰 숫자여야 함")
    elif p.paper.width_mm > p.paper.height_mm:
        err("PRESET_PAPER", "paper.width_mm은 세로 기준 폭(작은 값)이어야 함. 가로는 orientation으로 지정")
    if p.orientation not in ("portrait", "landscape"):
        err("PRESET_ORIENTATION", "orientation은 portrait 또는 landscape")

    m = p.margins_mm
    mvals = [m.top, m.header, m.bottom, m.footer, m.left, m.right, m.gutter]
    margins_ok = all(_num(v) for v in mvals)
    if not margins_ok:
        err("PRESET_MARGINS", "여백은 숫자여야 함")
    elif any(v < 0 for v in mvals):
        err("PRESET_MARGINS", "여백은 0 이상이어야 함")
        margins_ok = False

    c = p.columns
    cols_ok = isinstance(c.count, int) and not isinstance(c.count, bool) and 1 <= c.count <= 3
    if not cols_ok:
        err("PRESET_COLUMNS", "단 수는 1~3")
    if c.gap_mm is not None and not (_num(c.gap_mm) and c.gap_mm >= 0):
        err("PRESET_COLUMNS", "단 간격은 0 이상의 숫자 또는 null")
        cols_ok = False

    if not isinstance(c.divider, bool):
        err("PRESET_COLUMNS", "단 구분선은 true 또는 false")
    if not isinstance(p.page_number.enabled, bool):
        err("PRESET_PAGE_NUMBER", "쪽 번호는 true 또는 false")

    t = p.typography
    if not (isinstance(t.font_name, str) and t.font_name.strip()) or any(ord(ch) < 32 for ch in str(t.font_name)):
        err("PRESET_FONT", "글꼴 이름이 비어 있거나 잘못됨")
    if not (_num(t.font_size_pt) and 6 <= t.font_size_pt <= 20):  # [제안]
        err("PRESET_FONT_SIZE", "글자 크기는 6~20pt")
    if not (_num(t.equation_size_pt) and 6 <= t.equation_size_pt <= 20):  # [제안]
        err("PRESET_EQUATION_SIZE", "수식 크기는 6~20pt")
    if not (isinstance(t.line_spacing_pct, int) and not isinstance(t.line_spacing_pct, bool)
            and 100 <= t.line_spacing_pct <= 250):  # [제안]
        err("PRESET_LINE_SPACING", "줄 간격은 100~250%의 정수")
    if t.align not in ("auto", "left", "justify"):
        err("PRESET_ALIGN", "align은 auto/left/justify")

    n = p.numbering
    if n.mode not in ("sequence", "source"):
        err("PRESET_NUMBERING", "numbering.mode는 sequence/source")
    if not (isinstance(n.start, int) and not isinstance(n.start, bool)):
        err("PRESET_NUMBERING", "numbering.start는 정수")
    else:
        try:
            n.format.format(n=n.start)
        except Exception:
            err("PRESET_NUMBERING", "numbering.format은 '{n:02d}'처럼 n을 쓰는 형식이어야 함")

    if p.spacing.between_problems != "blank_paragraph":
        err("PRESET_SPACING", "between_problems는 blank_paragraph만 지원")
    bl = p.spacing.blank_lines
    if not (isinstance(bl, int) and not isinstance(bl, bool) and 0 <= bl <= 20):  # [제안]
        err("PRESET_SPACING", "blank_lines는 0~20의 정수")
    if p.choices.layout != "auto":
        err("PRESET_CHOICES", "choices.layout은 auto만 지원")
    if p.equation.size_mode not in ("auto", "estimated"):
        err("PRESET_EQUATION", "equation.size_mode는 auto/estimated")
    if p.on_unconfirmed not in ("skip", "fail"):
        err("PRESET_ON_UNCONFIRMED", "on_unconfirmed는 skip/fail")

    # 계산이 필요한 검증(앞 항목이 유효할 때만)
    if paper_ok and margins_ok and cols_ok and p.orientation in ("portrait", "landscape") \
            and p.paper.width_mm <= p.paper.height_mm:
        short, long_ = p.paper.width_mm, p.paper.height_mm
        page_w_mm = short if p.orientation == "portrait" else long_
        page_h_mm = long_ if p.orientation == "portrait" else short
        body_mm = page_w_mm - m.left - m.right - m.gutter
        gap_mm = column_gap_hwp(p) * 25.4 / 7200
        col_mm = (body_mm - gap_mm * (c.count - 1)) / c.count
        if body_mm <= 0:
            err("PRESET_MARGINS", "좌우 여백·제본의 합이 용지 폭 이상")
        elif col_mm < 30:  # [제안]
            err("PRESET_COLUMN_WIDTH", f"단 폭이 {col_mm:.1f}mm로 30mm 미만")
        if m.top + m.header + m.bottom + m.footer >= page_h_mm * 0.5:  # [제안]
            err("PRESET_MARGINS", "위·머리말·아래·꼬리말 여백의 합이 용지 높이의 50% 이상")
    return e
