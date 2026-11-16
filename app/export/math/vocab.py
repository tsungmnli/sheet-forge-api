"""LaTeX → 한글 수식 스크립트 어휘표 (README 4.3.1).

본 제품은 한글과컴퓨터의 글 문서 파일(.hwp) 공개 문서를 참고하여 개발하였습니다.

status
  verified   사용자가 한글에서 렌더링을 확인한 표기(수식 갤러리 v1·v2, sample_symbols.hwpx).
  documented 한컴 공식 문서 기준이지만 렌더링 미확인. 기본값에서는 변환기가 막는다(6.7 방출 정책).
"""
VERIFIED = "verified"
DOCUMENTED = "documented"

# 문서 표기를 우선한다(README 4.3.1). 함수명은 소문자만 유효(LOG·LN·LIM은 이탤릭 글자로 렌더링됨).
SYMBOLS = {
    # 관계·연산
    "le": ("LEQ", VERIFIED), "ge": ("GEQ", VERIFIED), "ne": ("!=", VERIFIED),
    "pm": ("PLUSMINUS", VERIFIED), "times": ("times", VERIFIED), "div": ("DIVIDE", VERIFIED),
    "cdot": ("cdot", VERIFIED), "circ": ("CIRC", VERIFIED),
    "infty": ("inf", VERIFIED), "therefore": ("therefore", VERIFIED),
    "to": ("->", VERIFIED), "Rightarrow": ("RARROW", VERIFIED), "Leftrightarrow": ("LRARROW", VERIFIED),
    "forall": ("FORALL", VERIFIED),
    # 집합
    "in": ("IN", VERIFIED), "notin": ("notin", VERIFIED), "subset": ("SUBSET", VERIFIED),
    "cup": ("cup", VERIFIED), "cap": ("cap", VERIFIED), "emptyset": ("EMPTYSET", VERIFIED),
    "{": ("lbrace", VERIFIED), "}": ("rbrace", VERIFIED),
    # 기하
    "angle": ("angle", VERIFIED), "triangle": ("triangle", VERIFIED),
    # 큰 연산자 (아래·위 첨자와 함께 쓰임)
    "sum": ("sum", VERIFIED), "int": ("int", VERIFIED),
    # 그리스 소문자
    "alpha": ("alpha", VERIFIED), "beta": ("beta", VERIFIED), "theta": ("theta", VERIFIED), "pi": ("pi", VERIFIED),
    # --- 공식 문서 기준(렌더링 미확인) ---
    "exists": ("EXIST", DOCUMENTED), "supset": ("SUPSET", DOCUMENTED), "subseteq": ("SUBSETEQ", DOCUMENTED),
    "supseteq": ("SUPSETEQ", DOCUMENTED), "wedge": ("WEDGE", DOCUMENTED), "vee": ("VEE", DOCUMENTED),
    "equiv": ("EQUIV", DOCUMENTED), "sim": ("SIM", DOCUMENTED), "cong": ("CONG", DOCUMENTED),
    "approx": ("APPROX", DOCUMENTED), "perp": ("BOT", DOCUMENTED), "parallel": ("VERT", DOCUMENTED),
    "because": ("BECAUSE", DOCUMENTED), "cdots": ("cdots", DOCUMENTED), "ldots": ("LDOTS", DOCUMENTED),
    "prod": ("PROD", DOCUMENTED),
}
for _g in ("gamma", "delta", "epsilon", "zeta", "eta", "iota", "kappa", "lambda", "mu", "nu", "xi",
           "rho", "sigma", "tau", "upsilon", "phi", "chi", "psi", "omega"):
    SYMBOLS[_g] = (_g, DOCUMENTED)

# 함수명: 한글이 자동으로 곧은 글자로 표시한다. 소문자만 유효 [검증 v1 H04b·H05b·H06b].
FUNCS = {
    "sin": VERIFIED, "cos": VERIFIED, "tan": VERIFIED, "log": VERIFIED, "ln": VERIFIED,
    "lim": VERIFIED, "min": VERIFIED,
    "max": DOCUMENTED, "sec": DOCUMENTED, "csc": DOCUMENTED, "cot": DOCUMENTED, "exp": DOCUMENTED,
    "lg": DOCUMENTED, "gcd": DOCUMENTED, "det": DOCUMENTED, "mod": DOCUMENTED,
    "arcsin": DOCUMENTED, "arccos": DOCUMENTED, "arctan": DOCUMENTED,
    "sinh": DOCUMENTED, "cosh": DOCUMENTED, "tanh": DOCUMENTED,
}
# 함수명 뒤 얇은 공백(`)을 넣지 않는 것: lim은 갤러리 H06에서 넣지 않은 형태로 검증됨.
NO_THIN_SPACE = {"lim"}

# 한글 수식 편집기의 예약어. 연속한 영문자가 이 단어와 겹치면 변수가 명령으로 해석된다(xin → ξn).
# 변수는 항상 글자마다 공백으로 분리해 방출하므로 충돌이 생기지 않는다 [검증 v2 V07·V08].
_RESERVED = {"over", "atop", "sqrt", "root", "of", "rm", "it", "bold", "left", "right", "cases", "bar",
             "vec", "hat", "dot", "ddot", "under", "arch", "tilde", "check", "acute", "grave", "dyad",
             "matrix", "pmatrix", "bmatrix", "dmatrix", "choose", "binom", "scale", "from", "to",
             "if", "for", "and", "hom", "ker", "deg", "arg", "dim", "pr", "exp", "sum", "int", "prod",
             "in", "notin", "cup", "cap", "inf", "angle", "triangle", "mod", "times", "div", "cdot"}
RESERVED_WORDS = _RESERVED | {v[0].lower() for v in SYMBOLS.values()} | set(FUNCS)

# 유니코드로 들어오는 기호(OCR 출력 등) → 명령. 검증된 것만.
UNICODE_CMD = {
    "≤": "le", "≥": "ge", "≠": "ne", "±": "pm", "×": "times", "÷": "div", "·": "cdot", "∞": "infty",
    "∴": "therefore", "∈": "in", "∉": "notin", "⊂": "subset", "∪": "cup", "∩": "cap", "∅": "emptyset",
    "→": "to", "⇒": "Rightarrow", "⇔": "Leftrightarrow", "∠": "angle", "△": "triangle", "∘": "circ",
    "∀": "forall", "θ": "theta", "π": "pi", "α": "alpha", "β": "beta",
}

# 명령 별칭(정규화)
ALIASES = {
    "dfrac": "frac", "tfrac": "frac", "cfrac": "frac", "leq": "le", "geq": "ge", "neq": "ne",
    "rightarrow": "to", "implies": "Rightarrow", "iff": "Leftrightarrow", "lbrace": "{", "rbrace": "}",
    "varnothing": "emptyset", "dots": "ldots", "textrm": "mathrm", "text": "text", "mathbb": "mathbb",
    "lvert": "|", "rvert": "|", "overline": "overline", "bar": "overline", "displaystyle": "displaystyle",
}

SPACE_CMDS = {",": "`", ";": "~", ":": "~", " ": "~", "quad": "~~", "qquad": "~~~~", "!": ""}
