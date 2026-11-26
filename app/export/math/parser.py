"""LaTeX 토큰화 + 파서(AST). 정규식 치환이 아니라 파서로 만든다(README 4.3 — 중첩 분수·루트 안전성)."""
import re
from dataclasses import dataclass, field
from typing import NamedTuple

from . import vocab


class MathError(Exception):
    def __init__(self, message, pos=None):
        super().__init__(message)
        self.message, self.pos = message, pos


# ---------------------------------------------------------------- 토큰
class Tok(NamedTuple):
    kind: str   # cmd | var | num | sym | lbrace | rbrace | caret | under | amp | dbs | kor | end
    val: str
    pos: int


_NUM = re.compile(r"\d+(?:\.\d+)?")
_KOR = re.compile(r"[^\x00-\x7f]+")
_ASCII_SYMS = set("+-=<>()[]|,.!%:;/'*")


def lex(s: str, base: int = 0) -> list:
    toks, i, n = [], 0, len(s)
    while i < n:
        c = s[i]
        if c.isspace():
            i += 1
        elif c == "\\":
            m = re.compile(r"[A-Za-z]+").match(s, i + 1)
            if m:
                toks.append(Tok("cmd", m.group(0), base + i))
                i = m.end()
            elif i + 1 < n and s[i + 1] == "\\":
                toks.append(Tok("dbs", "\\\\", base + i))
                i += 2
            elif i + 1 < n:
                toks.append(Tok("cmd", s[i + 1], base + i))
                i += 2
            else:
                raise MathError("수식이 역슬래시로 끝남", base + i)
        elif c == "{":
            toks.append(Tok("lbrace", c, base + i)); i += 1
        elif c == "}":
            toks.append(Tok("rbrace", c, base + i)); i += 1
        elif c == "^":
            toks.append(Tok("caret", c, base + i)); i += 1
        elif c == "_":
            toks.append(Tok("under", c, base + i)); i += 1
        elif c == "&":
            toks.append(Tok("amp", c, base + i)); i += 1
        elif c.isdigit() and c.isascii():
            m = _NUM.match(s, i)
            toks.append(Tok("num", m.group(0), base + i)); i = m.end()
        elif c.isascii() and c.isalpha():
            toks.append(Tok("var", c, base + i)); i += 1
        elif c in vocab.UNICODE_CMD:
            toks.append(Tok("cmd", vocab.UNICODE_CMD[c], base + i)); i += 1
        elif c == "°":
            toks.append(Tok("sym", "°", base + i)); i += 1
        elif c.isascii() and c in _ASCII_SYMS:
            toks.append(Tok("sym", c, base + i)); i += 1
        elif not c.isascii():
            m = _KOR.match(s, i)
            run = m.group(0)
            j = 0
            while j < len(run) and run[j] not in vocab.UNICODE_CMD and run[j] != "°":
                j += 1
            if j == 0:  # 첫 글자가 기호(위에서 처리됨)일 수 없지만 방어
                raise MathError(f"지원하지 않는 문자: {c}", base + i)
            toks.append(Tok("kor", run[:j], base + i)); i += j
        else:
            raise MathError(f"지원하지 않는 문자: {c!r}", base + i)
    return toks


# ---------------------------------------------------------------- 노드
@dataclass
class Num:
    s: str


@dataclass
class Var:
    c: str


@dataclass
class Sym:
    script: str
    name: str = ""          # LaTeX 명령 이름(어휘표 키) 또는 리터럴 문자
    role: str = ""          # open | close | bar | comma | ""
    pos: int = 0


@dataclass
class Func:
    name: str


@dataclass
class Frac:
    num: list
    den: list


@dataclass
class Sqrt:
    body: list
    index: list | None = None


@dataclass
class Script:
    base: object            # 노드 또는 None(앞 요소 없음)
    sub: list | None = None
    sup: list | None = None


@dataclass
class Group:
    body: list


@dataclass
class Delim:
    open: str               # 스크립트 표기: ( [ lbrace |
    close: str
    body: list
    explicit: bool = False  # \left … \right


@dataclass
class TextN:
    s: str
    roman: bool = False


@dataclass
class Rm:
    body: list


@dataclass
class Cases:
    rows: list              # rows → cells → nodes


@dataclass
class Deco:
    kind: str               # bar | arch | vec | dyad | dot
    body: list


@dataclass
class Space:
    script: str


@dataclass
class Ctx:
    documented: list = field(default_factory=list)   # (이름, 위치)
    warnings: list = field(default_factory=list)


# 여는 기호 이름 → 닫는 기호 이름(Sym.name 기준. `\{`·`\}`의 name은 "{"·"}")
_OPEN = {"(": ")", "[": "]", "{": "}"}


class Parser:
    def __init__(self, toks, ctx: Ctx):
        self.t, self.i, self.ctx = list(toks), 0, ctx

    # -- 기본 도우미
    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else Tok("end", "", -1)

    def next(self):
        tok = self.peek()
        self.i += 1
        return tok

    def pos_end(self):
        return self.t[-1].pos + 1 if self.t else 0

    # -- 시퀀스
    def parse_seq(self, stop=("end",)):
        nodes = []
        while True:
            tok = self.peek()
            if tok.kind in stop:
                break
            if tok.kind == "rbrace":
                raise MathError("짝이 없는 }", tok.pos)
            if tok.kind in ("caret", "under"):
                nodes.append(self.parse_scripts(None))
                continue
            if tok.kind == "amp" or tok.kind == "dbs":
                raise MathError("& 또는 \\\\는 cases 안에서만 쓸 수 있음", tok.pos)
            atom = self.parse_atom()
            if atom is None:
                continue
            if self.peek().kind in ("caret", "under"):
                atom = self.parse_scripts(atom)
            nodes.append(atom)
        return pair_delims(nodes)

    def parse_scripts(self, base):
        sub = sup = None
        while self.peek().kind in ("caret", "under"):
            k = self.next()
            arg = self.parse_arg()
            if k.kind == "caret":
                if sup is not None:
                    raise MathError("위 첨자가 두 번 붙음", k.pos)
                sup = arg
            else:
                if sub is not None:
                    raise MathError("아래 첨자가 두 번 붙음", k.pos)
                sub = arg
        return Script(base, sub, sup)

    def parse_arg(self):
        tok = self.peek()
        if tok.kind == "lbrace":
            self.next()
            body = self.parse_seq(stop=("rbrace",))
            if self.peek().kind != "rbrace":
                raise MathError("{ 가 닫히지 않음", tok.pos)
            self.next()
            return body
        if tok.kind == "end":
            raise MathError("인수가 없음", tok.pos)
        if tok.kind == "num" and len(tok.val) > 1:  # \frac12 처럼 숫자 한 글자만 인수
            self.t[self.i] = Tok("num", tok.val[1:], tok.pos + 1)
            return [Num(tok.val[0])]
        atom = self.parse_atom()
        return [atom] if atom is not None else []

    # -- 원자
    def parse_atom(self):
        tok = self.next()
        k, v = tok.kind, tok.val
        if k == "num":
            return Num(v)
        if k == "var":
            return Var(v)
        if k == "kor":
            self.ctx.warnings.append("TEXT_IN_MATH: 수식 안의 한글은 작게 표시됨")
            return TextN(v)
        if k == "lbrace":
            body = self.parse_seq(stop=("rbrace",))
            if self.peek().kind != "rbrace":
                raise MathError("{ 가 닫히지 않음", tok.pos)
            self.next()
            return Group(body)
        if k == "sym":
            return self.sym(v, tok.pos)
        if k == "cmd":
            return self.command(v, tok)
        raise MathError(f"예상하지 못한 토큰 {v!r}", tok.pos)

    def sym(self, c, pos):
        if c == "°":
            return Sym("°", "°", pos=pos)
        if c in "+-=<>.!%":
            return Sym(c, c, pos=pos)
        if c == ",":
            return Sym(",", ",", "comma", pos)
        if c in "([":
            return Sym(c, c, "open", pos)
        if c in ")]":
            return Sym(c, c, "close", pos)
        if c == "|":
            return Sym("|", "|", "bar", pos)
        if c == "'":
            return self.documented("prime", pos, "prime")
        self.ctx.documented.append((c, pos))  # : ; / * — 렌더링 미확인
        return Sym(c, c, pos=pos)

    def documented(self, script, pos, name):
        self.ctx.documented.append((name, pos))
        return Sym(script, name, pos=pos)

    def command(self, name, tok):
        pos = tok.pos
        name = vocab.ALIASES.get(name, name)
        if name in vocab.SPACE_CMDS:
            s = vocab.SPACE_CMDS[name]
            return Space(s) if s else None
        if name == "displaystyle":
            return None
        if name == "frac":
            return Frac(self.parse_arg(), self.parse_arg())
        if name == "sqrt":
            index = None
            if self.peek().kind == "sym" and self.peek().val == "[":
                self.next()
                idx_toks = []
                while self.peek().kind not in ("end",) and not (self.peek().kind == "sym" and self.peek().val == "]"):
                    idx_toks.append(self.next())
                if self.peek().kind == "end":
                    raise MathError("[ 가 닫히지 않음", pos)
                self.next()
                index = Parser(idx_toks, self.ctx).parse_seq()
            return Sqrt(self.parse_arg(), index)
        if name in ("mathrm", "mathbb", "text"):
            return self.text_like(name, tok)
        if name in vocab.DECO_CMDS:
            return Deco(vocab.DECO_CMDS[name], self.parse_arg())   # bar·arch·vec·dyad·dot(순환소수)
        if name == "left":
            return self.left_right(pos)
        if name == "right":
            raise MathError("\\left 없는 \\right", pos)
        if name == "begin":
            return self.environment(pos)
        if name == "end":
            raise MathError("\\begin 없는 \\end", pos)
        if name in vocab.FUNCS:
            if vocab.FUNCS[name] == vocab.DOCUMENTED:
                self.ctx.documented.append((name, pos))
            return Func(name)
        if name in vocab.SYMBOLS:
            script, status = vocab.SYMBOLS[name]
            if status == vocab.DOCUMENTED:
                self.ctx.documented.append((name, pos))
            role = "open" if name == "{" else "close" if name == "}" else ""
            return Sym(script, name, role, pos)
        if name in ("%",):
            return Sym("%", "%", pos=pos)
        if name == "|":
            return Sym("|", "|", "bar", pos)
        raise MathError(f"지원하지 않는 명령 \\{name}", pos)

    # -- \text · \mathrm · \mathbb
    def text_like(self, name, tok):
        arg_tok = self.peek()
        if arg_tok.kind != "lbrace":
            raise MathError(f"\\{name}에는 {{…}}가 필요함", tok.pos)
        self.next()
        parts = []
        depth = 1
        while True:
            t = self.next()
            if t.kind == "end":
                raise MathError("{ 가 닫히지 않음", arg_tok.pos)
            if t.kind == "lbrace":
                depth += 1
            elif t.kind == "rbrace":
                depth -= 1
                if depth == 0:
                    break
            parts.append(t)
        sub = Parser(parts, self.ctx).parse_seq() if name != "text" else None
        if name == "text":
            text = _tokens_text(parts)
            if text.isascii() and text.replace(" ", "").isalpha():
                return Rm([Var(ch) for ch in text.replace(" ", "")])
            self.ctx.warnings.append("TEXT_IN_MATH: 수식 안의 글자는 따옴표 문자열로 방출")
            return TextN(text)
        return Rm(sub)

    # -- \left … \right
    def left_right(self, pos):
        o = self.next()
        open_s = _delim_script(o, pos, "open")
        body_toks, depth = [], 1
        while True:
            t = self.next()
            if t.kind == "end":
                raise MathError("\\left에 맞는 \\right가 없음", pos)
            if t.kind == "cmd" and t.val == "left":
                depth += 1
            if t.kind == "cmd" and t.val == "right":
                depth -= 1
                if depth == 0:
                    break
            body_toks.append(t)
        c = self.next()
        close_s = _delim_script(c, pos, "close")
        return Delim(open_s, close_s, Parser(body_toks, self.ctx).parse_seq(), explicit=True)

    # -- \begin{cases} … \end{cases}
    def environment(self, pos):
        if not (self.peek().kind == "lbrace"):
            raise MathError("\\begin 뒤에 환경 이름이 없음", pos)
        self.next()
        name = ""
        while self.peek().kind == "var":
            name += self.next().val
        if self.next().kind != "rbrace":
            raise MathError("환경 이름이 잘못됨", pos)
        if name != "cases":
            raise MathError(f"지원하지 않는 환경 {name} (행렬은 후속)", pos)
        body, depth = [], 1
        while True:
            t = self.next()
            if t.kind == "end":
                raise MathError("\\end{cases}가 없음", pos)
            if t.kind == "cmd" and t.val == "begin":
                depth += 1
            if t.kind == "cmd" and t.val == "end":
                depth -= 1
                if depth == 0:
                    break
            body.append(t)
        while self.peek().kind in ("lbrace", "var", "rbrace") and self.peek().kind != "end":
            tk = self.next()
            if tk.kind == "rbrace":
                break
        rows, row, cell = [], [], []
        for t in body:
            if t.kind == "dbs":
                row.append(cell); rows.append(row); row, cell = [], []
            elif t.kind == "amp":
                row.append(cell); cell = []
            else:
                cell.append(t)
        if cell or row:
            row.append(cell); rows.append(row)
        rows = [[Parser(c, self.ctx).parse_seq() for c in r] for r in rows if any(r)]
        if any(len(r) > 1 for r in rows):
            self.ctx.warnings.append("CASES_AMP_AS_SPACE: cases의 &는 공백(~~)으로 방출함 [제안]")
        return Cases(rows)


def _tokens_text(toks):
    """\\text{…} 안의 토큰을 문자열로 되돌린다. 렉서는 공백을 버리므로 토큰 사이 간격(pos)으로 공백을 복원한다."""
    out, end = [], None
    for t in toks:
        if end is not None and t.pos > end:
            out.append(" ")
        if t.kind in ("var", "num", "kor", "sym"):
            out.append(t.val)
            end = t.pos + len(t.val)
        elif t.kind in ("lbrace", "rbrace"):
            end = t.pos + 1
        elif t.kind == "cmd" and t.val == " ":
            out.append(" ")
            end = None
        else:
            end = None
    return "".join(out)


def _delim_script(tok, pos, role):
    v = tok.val
    if tok.kind == "sym" and v in "([":
        return v
    if tok.kind == "sym" and v in ")]":
        return v
    if tok.kind == "sym" and v == "|":
        return "|"
    if tok.kind == "cmd" and vocab.ALIASES.get(v, v) in ("{", "}"):
        return "lbrace" if vocab.ALIASES.get(v, v) == "{" else "rbrace"
    if tok.kind == "cmd" and v == "|":
        raise MathError("\\left\\| (이중선)은 지원하지 않음", pos)
    raise MathError("지원하지 않는 \\left/\\right 구분자", pos)


# ---------------------------------------------------------------- 괄호 짝짓기
def _closer_key(n):
    s = n.base if isinstance(n, Script) else n
    if isinstance(s, Sym) and s.role == "close":
        return s
    return None


def pair_delims(nodes):
    """일반 괄호·대괄호·{ }·절댓값을 Delim으로 묶는다(높이가 있으면 변환 단계에서 LEFT/RIGHT로 승격)."""
    out, stack = [], []   # stack: (out 위치, 여는 Sym)
    for n in nodes:
        if isinstance(n, Sym) and n.role == "open":
            stack.append((len(out), n))
            out.append(n)
            continue
        if isinstance(n, Sym) and n.role == "bar":
            if stack and stack[-1][1].role == "bar":
                idx, o = stack.pop()
                out[idx:] = [Delim("|", "|", out[idx + 1:])]
            else:
                stack.append((len(out), n))
                out.append(n)
            continue
        cl = _closer_key(n)
        if cl is not None and stack:
            idx, o = stack[-1]
            if o.role == "open" and _OPEN.get(o.name) == cl.name:
                stack.pop()
                d = Delim(o.script, cl.script, out[idx + 1:])
                out[idx:] = [Script(d, n.sub, n.sup) if isinstance(n, Script) else d]
                continue
        out.append(n)
    return out


def parse(latex: str, ctx: Ctx):
    toks = lex(latex)
    p = Parser(toks, ctx)
    nodes = p.parse_seq()
    return nodes
