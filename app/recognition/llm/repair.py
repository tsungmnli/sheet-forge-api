"""B5-3a-1: 읽기 결과 후처리 (설계 6.4의 0번, LLM 호출 없음). 키트 normalize.py를 이식했고 이스케이프 복구를 더했다.
0) math 조각의 latex에서 제어문자(탭·폼피드·백스페이스·CR·LF)를 역슬래시 명령으로 되돌린다(모델이 JSON에서 역슬래시를 한 번만 써서 text 명령이 탭+ext로 풀리는 식의 경우).
1) text 조각 안의 독립된 영문 한 글자(변수)를 math 조각으로 뺀다.
2) math 조각 안의 한글을 text 조각으로 뺀다.
3) 이웃한 같은 종류의 조각을 합치고 빈 조각을 지운다. 줄 끝에서 쪼개진 문단을 합친다.
입력은 {"stem":[{"inlines":[...]}], "choices":[{"inlines":[...]}]|None, ...} 이고 제자리에서 고친다. 고친 조각 수를 돌려준다(내용 없이 숫자만 ocr_meta에 남긴다)."""
import re

_HANGUL = re.compile(r"([가-힣ㄱ-ㅎㅏ-ㅣ]+(?:[ \t]+[가-힣ㄱ-ㅎㅏ-ㅣ]+)*)")
_VAR = re.compile(r"(?<![A-Za-z\\])([A-Za-z])(?![A-Za-z])")
_PEEL_L, _PEEL_R = {"(": ")", "[": "]"}, {")": "(", "]": "["}


def _t(v): return {"t": "text", "v": v, "latex": None}
def _m(s): return {"t": "math", "v": None, "latex": s}


_CTRL = {"\t": "\\t", "\x0c": "\\f", "\x08": "\\b", "\r": "\\r", "\n": "\\n"}
_CTRL_RE = re.compile("[\t\x0c\x08\r\n]")


def _fix_escapes(inl):
    """latex에는 제어문자가 없으므로 되돌려도 손실이 없다. 고친 조각 수를 돌려준다."""
    n = 0
    for it in inl:
        if it.get("t") == "math" and it.get("latex") and _CTRL_RE.search(it["latex"]):
            it["latex"] = _CTRL_RE.sub(lambda m: _CTRL[m.group()], it["latex"])
            n += 1
    return n


def _split_vars(text):
    out, pos = [], 0
    for m in _VAR.finditer(text):
        if m.start() > pos: out.append(_t(text[pos:m.start()]))
        out.append(_m(m.group(1))); pos = m.end()
    if pos < len(text): out.append(_t(text[pos:]))
    return out


def _unmatched(piece):
    """짝 없는 ( ) [ ] 의 위치. 한글로 쪼갠 수식 조각의 괄호를 text로 돌려주려고 쓴다."""
    st, bad = [], set()
    for i, c in enumerate(piece):
        if c in "([": st.append((i, c))
        elif c in ")]":
            if st and st[-1][1] == {")": "(", "]": "["}[c]: st.pop()
            else: bad.add(i)
    bad.update(i for i, _ in st)
    return bad


def _math_with_brackets(piece):
    """수식 조각을 만들되 짝 없는 괄호는 text 조각으로 뺀다."""
    bad, out, buf = _unmatched(piece), [], ""
    for i, c in enumerate(piece):
        if i in bad:
            if buf.strip(): out.append(_m(buf.strip()))
            elif buf: out.append(_t(buf))
            out.append(_t(c)); buf = ""
        else:
            buf += c
    if buf.strip(): out.append(_m(buf.strip()))
    elif buf: out.append(_t(buf))
    return out


# 상자 \fbox/\boxed는 변환기가 못 받는다. \text{..}로 바꾼다 [B안: 상자 모양은 잃음]
_BOX = re.compile(r"\\text\{\\(?:fbox|boxed)\{([^{}]*)\}\}|\\(?:fbox|boxed)\{([^{}]*)\}")

_TEXTCMD = re.compile(r"\\(?:text|mathrm|mbox)\{([^{}]*)\}")


def _split_hangul(latex):
    if _BOX.search(latex) or "\\begin{" in latex:
        # cases 같은 환경이 쪼개지지 않도록 통째로 한 math로 둔다(수식 안 한글은 변환기가 작게 표시, 경고만)
        return [_m(_BOX.sub(lambda m: "\\text{" + (m.group(1) or m.group(2)) + "}", latex))]
    if not _HANGUL.search(latex):
        return [_m(latex)]
    # 한글이 든 \text{..}는 껍데기를 벗기고, \left/\right는 일반 괄호로 바꿔야 쪼갠 뒤에도 수식이 깨지지 않는다
    latex = _TEXTCMD.sub(lambda m: m.group(1) if _HANGUL.search(m.group(1)) else m.group(0), latex)
    latex = re.sub(r"\\(?:left|right)\s*\.", "", latex)
    latex = re.sub(r"\\(?:left|right)\s*", "", latex)
    out = []
    for part in _HANGUL.split(latex):
        if not part: continue
        if _HANGUL.fullmatch(part):
            out.append(_t(part)); continue
        ws_l, ws_r = part[:len(part) - len(part.lstrip())], part[len(part.rstrip()):]
        if ws_l: out.append(_t(ws_l))
        out += _math_with_brackets(part.strip())
        if ws_r: out.append(_t(ws_r))
    return out


def _merge(items):
    out = []
    for it in items:
        if it["t"] == "text":
            if not it["v"]: continue
            if out and out[-1]["t"] == "text":
                out[-1]["v"] += it["v"]; continue
        elif not (it.get("latex") or "").strip():
            continue
        out.append(it)
    return out


def _fix_inlines(inl):
    new = []
    for it in inl:
        if it["t"] == "text" and it.get("v"):
            new += _split_vars(it["v"])
        elif it["t"] == "math" and it.get("latex"):
            new += _split_hangul(it["latex"])
        else:
            new.append(it)
    new = _merge(new)
    changed = len(new) != len(inl) or any(a != b for a, b in zip(new, inl))
    return new, changed


_MARK = re.compile(r"^\s*(?:[ㄱ-ㅎ]\s*[.．]|\(\s*단|<\s*보기\s*>\s*$)")
_END = re.compile(r"[.?!)\]”\"'…]\s*$")


def _plain(inl): return "".join(i["v"] if i["t"] == "text" else "§" for i in inl)


def _merge_paragraphs(paras):
    """사진의 줄 끝에서 쪼개진 문단을 잇는다. 앞 문단이 한글 낱말로 끝나(문장이 안 끝남) 마지막 조각이 text이고,
    뒤 문단이 보기 기호(ㄱ.)·(단,·<보기> 제목으로 시작하지 않으면 한 문단으로 합친다."""
    out, n = [], 0
    for p in paras:
        if out:
            prev, cur = out[-1]["inlines"], p["inlines"]
            pt, ct = _plain(prev), _plain(cur)
            if prev and cur and prev[-1]["t"] == "text" and pt.strip() and not _END.search(pt) and not _MARK.match(ct):
                out[-1]["inlines"] = _merge(prev + [_t(" ")] + cur); n += 1
                continue
        out.append(p)
    paras[:] = out
    return n


def normalize_read(obj):
    n = 0
    for key in ("stem", "choices"):
        for para in obj.get(key) or []:
            n += _fix_escapes(para.get("inlines") or [])
            para["inlines"], ch = _fix_inlines(para.get("inlines") or [])
            n += ch
    n += _merge_paragraphs(obj.get("stem") or [])
    return n