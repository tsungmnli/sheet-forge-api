"""AST → 한글 수식 스크립트 방출 + 폭 추정 (README 4.3.1, 6.7).

방출 정책
- 토큰은 항상 공백으로 잇는다. 공백은 렌더링에 영향이 없고(4.3.1), 붙이면 `- >`가 `->`로,
  `x i n`이 `xin`(ξn)으로 합쳐지는 위험이 있다.
- 피연산자는 항상 `{}`로 감싼다. 연속 문자 변수는 글자마다 분리된다(Var 하나가 한 글자).
- 콤마 뒤에는 얇은 공백(`), 함수명 뒤에도 얇은 공백(lim, 그리고 `(`가 바로 오는 경우 제외).
- 높이가 있는 내용(분수·루트·cases·∑∫)을 감싼 괄호·절댓값, 명시적 \\left…\\right는 LEFT/RIGHT.
"""
from . import vocab
from .parser import (Cases, Deco, Delim, Frac, Func, Group, MathError, Num, Rm, Script, Space,
                     Sqrt, Sym, TextN, Var)

THIN = "`"
_BIG = {"sum", "int", "prod"}          # 아래·위 첨자가 위아래로 놓이는 큰 연산자
_NINE = 9                              # 9자 규칙(공식 문서): 공백 없이 이어진 항이 9자를 넘으면 따옴표


# ---------------------------------------------------------------- 높이 판정
def _tall_seq(nodes):
    return any(_tall_node(n) for n in nodes)


def _tall_node(n):
    if isinstance(n, (Frac, Sqrt, Cases)):
        return True
    if isinstance(n, Sym):
        return n.name in _BIG
    if isinstance(n, Script):
        if n.base is not None and _tall_node(n.base):
            return True
        if isinstance(n.base, Func) and n.base.name == "lim" and n.sub is not None:
            return True
        return _tall_seq(n.sub or []) or _tall_seq(n.sup or [])
    if isinstance(n, Delim):
        return _tall_seq(n.body)
    if isinstance(n, (Group, Rm, Deco)):
        return _tall_seq(n.body)
    return False


# ---------------------------------------------------------------- 방출
def _base_of(n):
    return n.base if isinstance(n, Script) else n


def _no_thin_after(nxt):
    """함수명 바로 뒤에 올 때 얇은 공백이 필요 없는 노드."""
    b = _base_of(nxt)
    if isinstance(b, (Delim, Space)):
        return True
    return isinstance(b, Sym) and b.role in ("open", "close", "comma", "bar")


def emit_seq(nodes, top=False):
    """top=True: 수식 전체의 최상위. 맨 끝의 rm은 it으로 닫지 않는다(끝에 오면 it 불필요 — v2 V05·V06)."""
    parts = []
    for i, n in enumerate(nodes):
        if top and i == len(nodes) - 1 and isinstance(n, Rm):
            s = "rm " + emit_seq(n.body)
        else:
            s = emit_node(n)
        if s:
            parts.append(s)
        b = _base_of(n)
        if isinstance(b, Func) and b.name not in vocab.NO_THIN_SPACE:
            nxt = nodes[i + 1] if i + 1 < len(nodes) else None
            if nxt is not None and not _no_thin_after(nxt):
                parts.append(THIN)
    return " ".join(parts)


def _is_circ(seq):
    return len(seq) == 1 and isinstance(seq[0], Sym) and seq[0].name in ("circ", "°")


def emit_node(n):
    if isinstance(n, Num):
        return f'"{n.s}"' if len(n.s) > _NINE else n.s
    if isinstance(n, Var):
        return n.c
    if isinstance(n, Sym):
        return ",`" if n.role == "comma" else n.script
    if isinstance(n, Func):
        return n.name
    if isinstance(n, Space):
        return n.script
    if isinstance(n, Frac):
        return "{" + emit_seq(n.num) + "} over {" + emit_seq(n.den) + "}"
    if isinstance(n, Sqrt):
        if n.index is None:
            return "sqrt {" + emit_seq(n.body) + "}"
        return "root {" + emit_seq(n.index) + "} of {" + emit_seq(n.body) + "}"
    if isinstance(n, Script):
        base = "{}" if n.base is None else emit_node(n.base)
        if n.base is not None and n.sub is None and n.sup is not None and _is_circ(n.sup):
            return base + "°"                                  # 30^\circ → 30° (4.3.1)
        parts = [base]
        if n.sub is not None:
            parts.append("_{" + emit_seq(n.sub) + "}")
        if n.sup is not None:
            parts.append("^{" + emit_seq(n.sup) + "}")
        return " ".join(parts)
    if isinstance(n, Group):
        return "{" + emit_seq(n.body) + "}"
    if isinstance(n, Delim):
        inner = emit_seq(n.body)
        if n.explicit or _tall_seq(n.body):
            return f"LEFT {n.open} {inner} RIGHT {n.close}"
        return f"{n.open} {inner} {n.close}"
    if isinstance(n, TextN):
        if '"' in n.s:
            raise MathError('수식 안 글자에 따옴표(")를 쓸 수 없음')
        return f'"{n.s}"'
    if isinstance(n, Rm):
        return "rm " + emit_seq(n.body) + " it"                # rm 구간은 항상 it으로 닫음(6.7)
    if isinstance(n, Cases):
        rows = [" ~~ ".join(emit_seq(c) for c in r) for r in n.rows]
        return "cases{" + " # ".join(rows) + "}"
    if isinstance(n, Deco):
        return n.kind + " {" + emit_seq(n.body) + "}"          # bar | arch | vec | dyad | dot
    raise MathError(f"방출할 수 없는 노드 {type(n).__name__}")


# ---------------------------------------------------------------- 폭 추정 [제안]
# 단위: em(기준 글자 크기 대비, 한글 sz 1000 HWPUNIT = 1em). 갤러리 v1의 hangul_w 81건에서 손으로 맞춘 초기값이다.
# 다시 맞추려면 scripts/fit_math_width.py 를 실행한다(README 6.7: AST 기반 모델로 재피팅).
W = {"digit": 0.5, "var": 0.48, "op": 1.25, "op_rel": 1.46, "sign": 0.8, "greek": 0.58, "big": 1.0,
     "paren": 0.45, "paren_tall": 0.5, "bar": 0.225, "comma": 0.5, "degree": 0.5, "punct": 0.3,
     "percent": 0.8, "rel": 1.5, "func_char": 0.5, "thin": 0.17, "text_kor": 0.6, "text_ascii": 0.5,
     "frac_pad": 0.4, "sqrt_pad": 0.9, "root_idx": 0.1, "script": 0.75, "cases_pad": 0.57,
     "cell_gap": 1.0, "rm_pad": 0.55, "deco_pad": 0.72}
# 기호별 폭(스크립트 표기 기준). 여기 없는 기호는 아래 규칙으로 추정한다.
SYM_W = {"LEQ": 1.62, "GEQ": 1.62, "!=": 1.48, "PLUSMINUS": 1.12, "times": 1.12, "DIVIDE": 1.12, "cdot": 1.06,
         "->": 1.19, "IN": 1.52, "notin": 1.79, "SUBSET": 2.08, "cup": 1.66, "cap": 1.66, "inf": 1.05,
         "therefore": 1.05, "EMPTYSET": 1.05, "angle": 1.85, "triangle": 1.85, "CIRC": 1.17,
         "lbrace": 0.54, "rbrace": 0.54, "int": 1.47}
# 함수명 폭(뒤따르는 얇은 공백 포함). 없는 함수는 func_char × 글자 수.
FUNC_W = {"sin": 1.45, "cos": 1.45, "tan": 1.5, "log": 1.46, "ln": 1.02, "lim": 1.5, "min": 1.8}
_SPACE_W = {"`": W["thin"], "~": 0.5, "~~": 1.0, "~~~~": 2.0}
_STACKED = {"sum", "prod"}                     # 첨자가 위아래로 놓이는 큰 연산자(∫은 옆에 붙는다)
_SIGN_PREV = {"=", "<", ">", "+", "-", "->"}    # 이 뒤의 +/-는 부호(좁게 표시)


def _w_sym(n, unary=False):
    if n.role == "comma":
        return W["comma"]
    if n.role in ("open", "close"):
        return W["paren"]
    if n.role == "bar":
        return W["bar"]
    if n.script in SYM_W:
        return SYM_W[n.script]
    if n.script == "°":
        return W["degree"]
    if n.script in ("+", "-"):
        return W["sign"] if unary else W["op"]
    if n.script == "=":
        return W["op"]
    if n.script in ("<", ">"):
        return W["op_rel"]
    if n.name in _STACKED:
        return W["big"]
    if n.script == "%":
        return W["percent"]
    if n.script in (".", "!", "prime"):
        return W["punct"]
    if n.script.isalpha() and n.script.islower():
        return W["greek"]
    return W["rel"]


def _is_unary(nodes, i):
    n = nodes[i]
    if not (isinstance(n, Sym) and n.script in ("+", "-")):
        return False
    if i == 0:
        return True
    p = nodes[i - 1]
    return isinstance(p, Sym) and (p.role in ("open", "comma") or p.script in _SIGN_PREV)


def node_widths(nodes):
    """노드별 폭(em). 부호 판정은 전체 문맥에서 한다(줄바꿈 뒤 첫 노드도 문맥 기준 폭을 유지)."""
    return [w_node(n, _is_unary(nodes, i)) for i, n in enumerate(nodes)]


def w_seq(nodes):
    return sum(node_widths(nodes))


def w_node(n, unary=False):
    if isinstance(n, Num):
        return W["digit"] * len(n.s.replace(".", "")) + (W["punct"] if "." in n.s else 0)
    if isinstance(n, Var):
        return W["var"]
    if isinstance(n, Sym):
        return _w_sym(n, unary)
    if isinstance(n, Func):
        return FUNC_W.get(n.name, W["func_char"] * len(n.name))
    if isinstance(n, Space):
        return _SPACE_W.get(n.script, 0.0)
    if isinstance(n, Frac):
        return max(w_seq(n.num), w_seq(n.den)) + W["frac_pad"]
    if isinstance(n, Sqrt):
        return w_seq(n.body) + W["sqrt_pad"] + (W["root_idx"] * w_seq(n.index) if n.index else 0.0)
    if isinstance(n, Script):
        base = 0.0 if n.base is None else w_node(n.base)
        if n.base is not None and n.sub is None and n.sup is not None and _is_circ(n.sup):
            return base + W["degree"]
        sub = w_seq(n.sub) if n.sub else 0.0
        sup = w_seq(n.sup) if n.sup else 0.0
        stacked = (isinstance(n.base, Sym) and n.base.name in _STACKED) or \
                  (isinstance(n.base, Func) and n.base.name == "lim")
        if stacked:
            return max(base, W["script"] * max(sub, sup))
        return base + W["script"] * max(sub, sup)
    if isinstance(n, Group):
        return w_seq(n.body)
    if isinstance(n, Rm):
        return w_seq(n.body) + W["rm_pad"]
    if isinstance(n, Deco):
        return w_seq(n.body) + (0 if n.kind == "dot" else W["deco_pad"])
    if isinstance(n, Delim):
        if n.open == "|":
            side = W["bar"]
        else:
            side = W["paren_tall"] if (n.explicit or _tall_seq(n.body)) else W["paren"]
        return w_seq(n.body) + 2 * side
    if isinstance(n, TextN):
        return sum(W["text_ascii"] if c.isascii() else W["text_kor"] for c in n.s)
    if isinstance(n, Cases):
        rows = [sum(w_seq(c) for c in r) + W["cell_gap"] * max(len(r) - 1, 0) for r in n.rows]
        return W["cases_pad"] + (max(rows) if rows else 0.0)
    return 0.0


def est_width(nodes):
    return round(w_seq(nodes), 3)
