"""수식 `#` 줄바꿈 계획 (README 4.6, 설계 10장).

규칙
- 줄바꿈 위치는 최상위(`{ }`·분수·루트·괄호 바깥)의 `+`, `-`, `=` 바로 앞에서만 [검증 4.6 `#`, 위치 정책은 제안].
- 부호로 쓰인 `+`/`-`(맨 앞, 여는 괄호·콤마·`=` 뒤)와 함수명 바로 뒤는 후보에서 뺀다.
- 사용자 지정 위치가 있으면 그대로 쓰고, 없으면 넘칠 때만 탐욕으로 정한다:
  각 줄에서 `max_em` 안에 들어가는 가장 오른쪽 후보에서 끊는다. 들어가는 후보가 없으면 가장 가까운 후보에서 끊고 too_wide로 표시한다.
- 사용자 지정은 "후보 번호"(0부터, 왼쪽에서 오른쪽 순서)로 받는다. 후보 번호는 break_candidates()의 순서다.
"""
from dataclasses import dataclass, field

from .emit import emit_seq, node_widths
from .parser import Func, Sym

BREAK_BEFORE = frozenset({"+", "-", "="})
_SIGN_PREV = frozenset({"=", "<", ">", "+", "-", "->"})
_EPS = 1e-9


def _is_sign(nodes, i):
    """nodes[i]가 부호(단항)로 쓰인 +/- 인가. emit._is_unary와 같은 규칙이다."""
    if i == 0:
        return True
    p = nodes[i - 1]
    return isinstance(p, Sym) and (p.role in ("open", "comma") or p.script in _SIGN_PREV)


def break_candidates(nodes) -> list:
    """`#`을 넣을 수 있는 최상위 노드 인덱스(해당 노드 바로 앞에 넣는다). 왼쪽에서 오른쪽 순서."""
    out = []
    for i, n in enumerate(nodes):
        if i == 0 or not isinstance(n, Sym) or n.script not in BREAK_BEFORE:
            continue
        if n.script in ("+", "-") and _is_sign(nodes, i):
            continue
        if isinstance(nodes[i - 1], Func):
            continue
        out.append(i)
    return out


@dataclass
class WrapPlan:
    cuts: list = field(default_factory=list)          # `#`을 넣을 노드 인덱스(앞에 넣음)
    chosen: list = field(default_factory=list)        # 적용된 후보 번호
    auto: bool = False                                # 자동으로 정했는가(사용자 지정이 아님)
    too_wide: bool = False                            # 줄바꿈 후에도 max_em을 넘는 줄이 있음
    line_widths: list = field(default_factory=list)   # 줄별 추정 폭(em)
    ignored: list = field(default_factory=list)       # 범위를 벗어나 무시한 사용자 지정 번호
    candidates: int = 0


def plan_wrap(nodes, max_em: float = float("inf"), user_breaks=None) -> WrapPlan:
    """user_breaks=None이면 자동, 리스트면(빈 리스트 포함) 그 위치만 쓴다."""
    w = node_widths(nodes)
    pre = [0.0]
    for x in w:
        pre.append(pre[-1] + x)
    n = len(nodes)
    cands = break_candidates(nodes)
    plan = WrapPlan(candidates=len(cands))

    if user_breaks is not None:
        good = sorted({k for k in user_breaks if isinstance(k, int) and not isinstance(k, bool) and 0 <= k < len(cands)})
        plan.ignored = [k for k in user_breaks if k not in good]
        plan.chosen, plan.cuts = good, [cands[k] for k in good]
    elif pre[n] > max_em:
        s, cuts = 0, []
        while pre[n] - pre[s] > max_em:
            avail = [c for c in cands if c > s]
            if not avail:
                break
            fit = [c for c in avail if pre[c] - pre[s] <= max_em]
            c = fit[-1] if fit else avail[0]
            cuts.append(c)
            s = c
        plan.cuts = cuts
        plan.chosen = [cands.index(c) for c in cuts]
        plan.auto = bool(cuts)

    bounds = [0] + plan.cuts + [n]
    plan.line_widths = [round(pre[b] - pre[a], 3) for a, b in zip(bounds, bounds[1:])]
    plan.too_wide = any(lw > max_em + _EPS for lw in plan.line_widths)
    return plan


def emit_wrapped(nodes, cuts) -> str:
    """cuts 앞에 `#`을 넣어 방출. cuts가 비면 emit_seq(top=True)와 같다."""
    bounds = [0] + list(cuts) + [len(nodes)]
    segs = [nodes[a:b] for a, b in zip(bounds, bounds[1:])]
    return " # ".join(emit_seq(seg, top=(k == len(segs) - 1)) for k, seg in enumerate(segs))
