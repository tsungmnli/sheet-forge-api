"""LaTeX → 한글 수식 스크립트 변환 진입점 (README 6.7, 설계 10장).

본 제품은 한글과컴퓨터의 글 문서 파일(.hwp) 공개 문서를 참고하여 개발하였습니다.

실패해도 예외를 던지지 않고 ok=False와 오류 위치를 돌려준다.
렌더링 미확인(documented) 어휘는 기본적으로 막는다(allow_documented=True면 허용: 갤러리 v3 생성용).
"""
from dataclasses import dataclass, field

from .emit import est_width
from .parser import Ctx, MathError, parse
from .wrap import emit_wrapped, plan_wrap


@dataclass
class ConvertResult:
    script: str
    ok: bool
    warnings: list = field(default_factory=list)
    error: str | None = None
    error_pos: int | None = None
    est_width_em: float = 0.0
    documented: list = field(default_factory=list)   # [(이름, 위치)] 렌더링 미확인 어휘
    # 줄바꿈(`#`) 계획 — max_width_em 또는 breaks를 줬을 때만 채워진다(wrap.py)
    breaks: list = field(default_factory=list)        # 적용된 후보 번호(왼쪽→오른쪽)
    auto_broken: bool = False                         # `#`을 자동으로 넣었는가
    too_wide: bool = False                            # 줄바꿈 후에도 max_width_em을 넘는 줄이 있는가
    line_widths_em: list = field(default_factory=list)
    break_candidates: int = 0                         # 끊을 수 있는 후보 수(최상위 +, -, = 앞)
    ignored_breaks: list = field(default_factory=list)


def _dedup(items):
    seen, out = set(), []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def convert(latex: str, allow_documented: bool = False, *, max_width_em: float | None = None,
            breaks: list | None = None) -> ConvertResult:
    """max_width_em: 한 줄에 허용할 추정 폭(em). 넘으면 `#`을 자동 삽입한다.
    breaks: 사용자 지정 줄바꿈 후보 번호 리스트(빈 리스트 = 줄바꿈 없음). 주면 자동 삽입보다 우선한다.
    둘 다 None이면 줄바꿈을 하지 않는다(기존 동작)."""
    ctx = Ctx()
    if not latex or not latex.strip():
        return ConvertResult("", False, error="빈 수식", error_pos=0)
    try:
        nodes = parse(latex, ctx)
        documented = list(ctx.documented)
        if documented and not allow_documented:
            names = ", ".join(sorted({n for n, _ in documented}))
            first = min(p for _, p in documented)
            return ConvertResult("", False, _dedup(ctx.warnings), f"렌더링 미확인 기호: {names}",
                                 first, 0.0, documented)
        plan = plan_wrap(nodes, float("inf") if max_width_em is None else max_width_em, breaks)
        script = emit_wrapped(nodes, plan.cuts)
        warnings = _dedup(ctx.warnings)
        if plan.ignored:
            warnings.append(f"BREAK_IGNORED: 줄바꿈 후보 번호 {plan.ignored}는 범위(0~{plan.candidates - 1})를 벗어나 무시함")
        return ConvertResult(script, True, warnings, None, None, est_width(nodes), documented,
                             plan.chosen, plan.auto, plan.too_wide, plan.line_widths, plan.candidates, plan.ignored)
    except MathError as e:
        return ConvertResult("", False, _dedup(ctx.warnings), e.message, e.pos, 0.0, list(ctx.documented))
