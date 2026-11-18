"""B5-5d: to_content가 저장 전에 맞추는 것(제목 기본값·자르기·표 직사각형)과 API 한계와의 일치 (LLM 호출 없음)."""
from app.api import stem_blocks as sb
from app.recognition.llm import content as c
from app.recognition.llm.content import count_clamped, to_content


def _t(v):
    return {"t": "text", "v": v, "latex": None}


def _box(n, title="<보기>"):
    return {"type": "box", "title": title, "paragraphs": [{"inlines": [_t("ㄱ")]} for _ in range(n)]}


def _table(rows):
    return {"type": "table", "rows": rows}


def _stem(*blocks):
    return {"stem": list(blocks), "choices": None}


def test_limits_match_api():
    assert (c.BOX_TITLE_DEFAULT, c.MAX_TITLE, c.MAX_BOX_LINES, c.MAX_TABLE_ROWS, c.MAX_TABLE_COLS) == (
        sb.BOX_TITLE_DEFAULT, sb.MAX_TITLE, sb.MAX_BOX_LINES, sb.MAX_TABLE_ROWS, sb.MAX_TABLE_COLS)


def test_box_title_default_and_truncate():
    assert to_content(_stem(_box(1, None)))["stem"][0]["title"] == "<보기>"
    assert to_content(_stem(_box(1, "  ")))["stem"][0]["title"] == "<보기>"
    assert to_content(_stem(_box(1, "가" * 25)))["stem"][0]["title"] == "가" * 20


def test_box_lines_clipped():
    assert len(to_content(_stem(_box(c.MAX_BOX_LINES + 5)))["stem"][0]["paragraphs"]) == c.MAX_BOX_LINES


def test_table_clipped_and_padded_rectangular():
    wide = [[_t("a")] for _ in range(c.MAX_TABLE_COLS + 2)]
    rows = to_content(_stem(_table([wide] + [[[_t("b")]]] * (c.MAX_TABLE_ROWS + 1))))["stem"][0]["rows"]
    assert len(rows) == c.MAX_TABLE_ROWS
    assert {len(r) for r in rows} == {c.MAX_TABLE_COLS}
    assert rows[1][0] == [{"t": "text", "v": "b"}] and rows[1][1] == []


def test_short_rows_are_padded_with_empty_cells():
    rows = to_content(_stem(_table([[[_t("a")], [_t("b")]], [[_t("c")]]])))["stem"][0]["rows"]
    assert rows == [[[{"t": "text", "v": "a"}], [{"t": "text", "v": "b"}]], [[{"t": "text", "v": "c"}], []]]


def test_count_clamped():
    ok = _stem(_box(2), _table([[[_t("a")]]]))
    assert count_clamped(ok) == 0
    bad = _stem(_box(c.MAX_BOX_LINES + 1), _box(1, "가" * 21), _table([[[_t("a")]]] * (c.MAX_TABLE_ROWS + 1)),
                _table([[[_t("a")]] * (c.MAX_TABLE_COLS + 1)]), {"inlines": [_t("문단")]})
    assert count_clamped(bad) == 4
