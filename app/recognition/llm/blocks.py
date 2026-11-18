"""B5-5b: 읽기 결과 stem·choices 안의 조각 목록을 한 곳에서 훑는다(문단·상자 줄·표 칸). LLM 호출 없음.
- 문단은 {"inlines"}(type 없음 또는 paragraph), 상자는 {"type":"box","title","paragraphs":[{"inlines"}]},
  표는 {"type":"table","rows":[행 -> 칸 -> 조각 목록]}이다. choices에는 문단만 있다.
- 위치(pos)는 {"area","para"}에 상자 줄이면 "p", 표 칸이면 "r"·"c"를 더한 것이다. 문단은 예전과 같은 모양이다.
  para는 area 안의 블록 번호이고, 조각 번호(inline)는 부르는 쪽이 붙인다."""


def is_para(b: dict) -> bool:
    return b.get("type") in (None, "paragraph")


def iter_inlines(obj: dict):
    """(pos, 컨테이너, 키)를 돌려준다. 조각 목록은 컨테이너[키]이고, 부르는 쪽이 읽거나 새 목록으로 바꿔 넣을 수 있다."""
    for area in ("stem", "choices"):
        for pi, blk in enumerate(obj.get(area) or []):
            t = blk.get("type")
            if t == "box":
                for qi, q in enumerate(blk.get("paragraphs") or []):
                    yield {"area": area, "para": pi, "p": qi}, q, "inlines"
            elif t == "table":
                for ri, row in enumerate(blk.get("rows") or []):
                    for ci in range(len(row)):
                        yield {"area": area, "para": pi, "r": ri, "c": ci}, row, ci
            else:
                yield {"area": area, "para": pi}, blk, "inlines"


def inlines_of(cont, key) -> list:
    v = cont.get(key) if isinstance(cont, dict) else cont[key]
    return v or []


def inline_at(obj: dict, pos: dict) -> dict:
    """pos(area, para, [p | r, c], inline)가 가리키는 조각 dict."""
    blk = obj[pos["area"]][pos["para"]]
    if "p" in pos:
        lst = blk["paragraphs"][pos["p"]]["inlines"]
    elif "r" in pos:
        lst = blk["rows"][pos["r"]][pos["c"]]
    else:
        lst = blk["inlines"]
    return lst[pos["inline"]]
