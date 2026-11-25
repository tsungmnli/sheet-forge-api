"""stem 블록 종류별 모양과 순회 (DB 없음). 문단(paragraph)·상자(box)·표(table).

저장 모양:
  {"type":"paragraph", "inlines":[...]}
  {"type":"box",   "title":"<보기>" | "", "paragraphs":[{"inlines":[...]}, ...]}   # title이 ""이면 제목 없는 상자(조건 상자)
  {"type":"table", "rows":[[[inline, ...], ...], ...]}        # 셀 = 조각 목록(선택지 한 개와 같은 모양), 모든 행의 칸 수가 같다
조각 위치(path)는 웹이 그 자리로 이동하는 데 쓴다:
  stem/{b}/inlines/{i}  ·  stem/{b}/paragraphs/{p}/inlines/{i}  ·  stem/{b}/rows/{r}/{c}/{i}
"""

MAX_BOX_LINES = 30
MAX_TITLE = 20
MAX_TABLE_ROWS = 40
MAX_TABLE_COLS = 8


def inline_list(x) -> list:
    """문단({"inlines":[...]}) 또는 조각 목록 → 조각 목록. 그 밖의 값은 빈 목록."""
    if isinstance(x, dict):
        x = x.get("inlines")
    return x if isinstance(x, list) else []


def block_groups(block: dict):
    """블록 하나의 '글 묶음' 목록: 문단은 하나, 상자는 줄마다, 표는 칸마다. 각 묶음은 조각 목록."""
    t = block.get("type") or "paragraph"
    if t == "box":
        for p in block.get("paragraphs") or []:
            yield inline_list(p)
    elif t == "table":
        for row in block.get("rows") or []:
            for cell in row or []:
                yield inline_list(cell)
    else:
        yield inline_list(block.get("inlines"))


def stem_groups(content: dict):
    """(묶음, 구분) 목록. 구분은 묶음 뒤에 평문으로 이을 때 넣을 문자: 문단은 \"\"(기존 동작 유지), 상자·표는 \" \"."""
    for block in content.get("stem") or []:
        sep = "" if (block.get("type") or "paragraph") == "paragraph" else " "
        for g in block_groups(block):
            yield g, sep


def iter_stem_inlines(content: dict):
    """(경로, 조각) 목록 — stem 전체."""
    for bi, block in enumerate(content.get("stem") or []):
        t = block.get("type") or "paragraph"
        if t == "box":
            for pi, p in enumerate(block.get("paragraphs") or []):
                for ii, inl in enumerate(inline_list(p)):
                    yield f"stem/{bi}/paragraphs/{pi}/inlines/{ii}", inl
        elif t == "table":
            for ri, row in enumerate(block.get("rows") or []):
                for ci, cell in enumerate(row or []):
                    for ii, inl in enumerate(inline_list(cell)):
                        yield f"stem/{bi}/rows/{ri}/{ci}/{ii}", inl
        else:
            for ii, inl in enumerate(block.get("inlines") or []):
                yield f"stem/{bi}/inlines/{ii}", inl


def normalize_block(block: dict, bad) -> dict:
    """box·table 블록을 저장 모양으로 맞춘다(문단이 조각 목록으로 오거나 행이 짧아도 받는다). 모양이 틀리면 bad(메시지)가 던지는 예외.
    paragraph와 알 수 없는 종류는 그대로 둔다(알 수 없는 종류는 내보낼 때 보고된다)."""
    t = block.get("type") or "paragraph"
    if t == "box":
        title = block.get("title")
        if title is None:
            title = ""      # 제목 없는 상자. <보기>를 대신 붙이지 않는다
        if not isinstance(title, str) or len(title) > MAX_TITLE:
            raise bad("상자 제목이 올바르지 않아요.")
        if not title.strip():
            title = ""
        paras = block.get("paragraphs") or []
        if not isinstance(paras, list) or len(paras) > MAX_BOX_LINES:
            raise bad("상자의 줄이 너무 많아요.")
        out = {k: v for k, v in block.items() if k != "inlines"}
        out.update(type="box", title=title, paragraphs=[{"inlines": _checked(inline_list(p), p, bad)} for p in paras])
        return out
    if t == "table":
        rows = block.get("rows") or []
        if not isinstance(rows, list) or len(rows) > MAX_TABLE_ROWS:
            raise bad("표의 행이 너무 많아요.")
        grid = []
        for row in rows:
            if not isinstance(row, list) or len(row) > MAX_TABLE_COLS:
                raise bad("표의 열이 너무 많거나 모양이 올바르지 않아요.")
            grid.append([_checked(inline_list(c), c, bad) for c in row])
        ncols = max((len(r) for r in grid), default=0)
        out = {k: v for k, v in block.items() if k != "inlines"}
        out.update(type="table", rows=[r + [[] for _ in range(ncols - len(r))] for r in grid])
        return out
    return block


def _checked(inlines: list, raw, bad) -> list:
    if (isinstance(raw, dict) and raw.get("inlines") is not None and not isinstance(raw["inlines"], list)) \
            or any(not isinstance(i, dict) for i in inlines):
        raise bad("내용 조각 모양이 올바르지 않아요.")
    return inlines
