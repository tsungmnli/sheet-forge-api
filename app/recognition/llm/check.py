"""B5-3b-2: 읽기 결과의 모든 math 조각을 수식 변환기로 점검한다(설계 6.4의 2~3). LLM 호출 없음.
입력은 read_crop의 정규화 결과(stem·choices가 문단 배열, 조각은 t/v/latex). 입력은 바꾸지 않는다.
- failures: 변환 불가(ok=False). 수리 호출(B5-3b-3)의 대상이며, 끝내 남으면 math_warning 힌트가 된다.
- warnings: 변환은 됐지만 변환기가 주의를 남긴 것(hints의 warn).
위치는 (area, para, inline) 번호로만 나타낸다(area: stem | choices, 0부터). 상자 줄이면 p, 표 칸이면 r·c가 더 붙는다(blocks.py). 로그에는 개수만 남기고 latex는 남기지 않는다."""
from dataclasses import dataclass, field

from ...export.math.convert import convert
from .blocks import inlines_of, iter_inlines


@dataclass
class MathCheck:
    failures: list = field(default_factory=list)   # {area, para, inline, latex, error, error_pos}
    warnings: list = field(default_factory=list)   # {area, para, inline, latex, warnings}


def _walk(obj: dict):
    for pos, cont, key in iter_inlines(obj):
        for ii, inl in enumerate(inlines_of(cont, key)):
            if inl.get("t") == "math":
                yield pos, ii, inl.get("latex") or ""


def check_math(obj: dict, convert_fn=convert) -> MathCheck:
    out = MathCheck()
    for loc, ii, latex in _walk(obj):
        pos = dict(loc, inline=ii, latex=latex)
        try:
            r = convert_fn(latex)
        except Exception:  # noqa: BLE001 — 변환기 내부 오류도 변환 불가로 본다(예외 내용은 남기지 않는다)
            out.failures.append(dict(pos, error="internal", error_pos=None))
            continue
        if not r.ok:
            out.failures.append(dict(pos, error=r.error, error_pos=r.error_pos))
        elif r.warnings:
            out.warnings.append(dict(pos, warnings=list(r.warnings)))
    return out
