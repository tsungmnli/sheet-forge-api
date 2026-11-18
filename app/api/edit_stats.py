"""B5-4a: 확인 시 고친 조각 수 세기(설계 12장). DB 없음.
recognized(기계가 읽은 결과)와 content(선생님이 확인한 내용)를 조각 단위로 비교한다.
- stem: 문단 안의 text·math 조각을 순서대로 늘어놓고(문단 사이에는 구분 표시) 비교한다. 바뀐 구간마다 종류별로 센다.
- choices: 선택지 하나를 한 조각으로 보고 비교한다.
- 결과는 숫자뿐이다(문제 내용·글자 없음). 공백 차이는 같은 것으로 본다.
- 그림은 서버가 관리하고 recognized에 없어 세지 않는다."""
from collections import Counter
from difflib import SequenceMatcher

from .stem_blocks import block_groups

KINDS = ("text", "math", "choices", "paragraphs")
_PARA = "paragraphs"


def _norm(s) -> str:
    return " ".join((s or "").split())


def _tok(inl: dict):
    t = inl.get("t")
    return (t, _norm(inl.get("v") if t == "text" else inl.get("latex")))


def _stem_tokens(content: dict) -> list:
    out = []
    for bi, block in enumerate(content.get("stem") or []):
        if bi:
            out.append((_PARA, ""))
        for gi, group in enumerate(block_groups(block)):   # 문단은 묶음 하나, 상자는 줄마다, 표는 칸마다
            if gi:
                out.append((_PARA, ""))
            out += [_tok(i) for i in group]
    return out


def _choice_keys(content: dict) -> list:
    items = (content.get("choices") or {}).get("items") or []
    return [tuple(_tok(i) for i in (item or [])) for item in items]


def _diff(a: list, b: list, kind_of) -> Counter:
    edited = Counter()
    for op, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        ca = Counter(kind_of(x) for x in a[i1:i2])
        cb = Counter(kind_of(x) for x in b[j1:j2])
        for k in set(ca) | set(cb):
            edited[k] += max(ca[k], cb[k])
    return edited


def count_edits(recognized: dict, content: dict) -> dict:
    ra, cb = recognized or {}, content or {}
    sa, sb = _stem_tokens(ra), _stem_tokens(cb)
    edited = _diff(sa, sb, lambda x: x[0])
    total = Counter(x[0] for x in sa)
    xa, xb = _choice_keys(ra), _choice_keys(cb)
    edited.update(_diff(xa, xb, lambda x: "choices"))
    total["choices"] = len(xa)
    shape = lambda c: {k: int(c.get(k, 0)) for k in KINDS}  # noqa: E731 - 키 모양을 항상 같게
    return {"edited": shape(edited), "of": shape(total)}
