"""B5-3b-1: 읽기 결과(read_crop의 정규화 결과) -> REST content 계약 (설계 6.3). 순수 함수, LLM 호출 없음.
- stem 문단에 type="paragraph"를 붙이고, 조각의 null 필드를 지운다(text는 t·v만, math는 t·latex만).
- stem의 box·table 블록은 type을 유지하고 조각을 같은 방식으로 정리한다. 저장 때 API가 하는 정리를 여기서 미리 한다: 상자 title이 없으면 <보기>, 20자 넘으면 자르고, 표는 짧은 행을 빈 칸으로 채워 직사각형으로 만든다.
- 상자 30줄, 표 40행×8열을 넘는 부분은 자른다(읽기 단계에서 걸러야 저장이 거절되지 않는다). 잘린 블록 수는 count_clamped가 센다.
- choices는 문단 배열 -> {"items": [조각 배열, ...], "layout": "auto"}. 선택지가 없으면 None.
- figures는 여기서 다루지 않는다. 크롭 좌표를 보정본 좌표로 바꾸고 그림 항목을 만드는 일은 이후 단계이며, 지금은 빈 목록이다.
- 입력은 바꾸지 않는다."""


def _inline(i: dict) -> dict:
    if i["t"] == "math":
        return {"t": "math", "latex": i["latex"]}
    return {"t": "text", "v": i["v"]}


def _inlines(p: dict) -> list:
    return [_inline(i) for i in p["inlines"]]


# app/api/stem_blocks.py의 한계와 같다(어긋나면 tests/recognition/test_b5_content_limits.py가 잡는다).
BOX_TITLE_DEFAULT, MAX_TITLE, MAX_BOX_LINES, MAX_TABLE_ROWS, MAX_TABLE_COLS = "<보기>", 20, 30, 40, 8


def _block(b: dict) -> dict:
    t = b.get("type", "paragraph")
    if t == "box":
        title = (b.get("title") or "").strip()[:MAX_TITLE].strip() or BOX_TITLE_DEFAULT
        return {"type": "box", "title": title,
                "paragraphs": [{"inlines": _inlines(p)} for p in b["paragraphs"][:MAX_BOX_LINES]]}
    if t == "table":
        rows = [[[_inline(i) for i in cell] for cell in row[:MAX_TABLE_COLS]] for row in b["rows"][:MAX_TABLE_ROWS]]
        width = max((len(r) for r in rows), default=0)
        for r in rows:
            r.extend([] for _ in range(width - len(r)))   # 빈 칸 = 빈 조각 목록
        return {"type": "table", "rows": rows}
    return {"type": "paragraph", "inlines": _inlines(b)}


def count_clamped(obj: dict) -> int:
    """한계를 넘어 to_content가 자르게 되는 상자·표의 수(제목 20자 초과 포함)."""
    n = 0
    for b in obj["stem"]:
        t = b.get("type")
        if t == "box":
            n += len((b.get("title") or "").strip()) > MAX_TITLE or len(b["paragraphs"]) > MAX_BOX_LINES
        elif t == "table":
            n += len(b["rows"]) > MAX_TABLE_ROWS or any(len(r) > MAX_TABLE_COLS for r in b["rows"])
    return int(n)


def to_content(obj: dict) -> dict:
    stem = [_block(b) for b in obj["stem"]]
    ch = obj.get("choices")
    choices = {"items": [_inlines(p) for p in ch], "layout": "auto"} if ch else None
    return {"stem": stem, "choices": choices, "figures": []}
