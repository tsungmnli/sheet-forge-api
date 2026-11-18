"""B5-5a: 읽기 JSON의 box·table 블록 파싱과 content 계약 변환 (LLM 호출 없음)."""
import copy
import json

import pytest

from app.recognition.llm.content import to_content
from app.recognition.llm.read import ReadParseError, parse_read_json


def _t(v):
    return {"t": "text", "v": v, "latex": None}


def _m(latex):
    return {"t": "math", "v": None, "latex": latex}


def _c(v):
    return {"t": "text", "v": v}


def _cm(latex):
    return {"t": "math", "latex": latex}


def _read(stem):
    return json.dumps({"stem": stem, "choices": None, "figures": [], "uncertain": [],
                       "unsupported_block": None, "points": None}, ensure_ascii=False)


def test_paragraph_type_is_optional_and_not_kept():
    a = parse_read_json(_read([{"inlines": [_t("가")]}]))
    b = parse_read_json(_read([{"type": "paragraph", "inlines": [_t("가")]}]))
    assert a["stem"] == b["stem"] == [{"inlines": [_t("가")]}]


def test_box_block():
    box = {"type": "box", "title": "<보기>", "paragraphs": [{"inlines": [_t("ㄱ. "), _m("x>0")]}]}
    assert parse_read_json(_read([box]))["stem"] == [box]


def test_box_without_title_keeps_none():
    out = parse_read_json(_read([{"type": "box", "paragraphs": [{"inlines": [_t("ㄱ")]}]}]))
    assert out["stem"][0]["title"] is None


def test_table_block_keeps_rows_cells_inlines():
    rows = [[[_t("x")], [_t("y")]], [[_m("1")], []]]
    assert parse_read_json(_read([{"type": "table", "rows": rows}]))["stem"] == [{"type": "table", "rows": rows}]


def test_empty_box_and_table_are_dropped():
    stem = [{"inlines": [_t("a")]},
            {"type": "box", "title": None, "paragraphs": []},
            {"type": "table", "rows": []},
            {"type": "table", "rows": [[]]}]
    assert parse_read_json(_read(stem))["stem"] == [{"inlines": [_t("a")]}]


@pytest.mark.parametrize("block", [
    {"type": "chart", "inlines": []},
    {"type": "box", "title": 3, "paragraphs": [{"inlines": []}]},
    {"type": "box", "title": None, "paragraphs": "x"},
    {"type": "table", "rows": "x"},
    {"type": "table", "rows": [["x"]]},
    "text",
])
def test_bad_block_shape(block):
    with pytest.raises(ReadParseError):
        parse_read_json(_read([block]))


def test_to_content_maps_paragraph_box_and_table():
    obj = {"stem": [
        {"inlines": [_t("다음 중")]},
        {"type": "box", "title": "<보기>", "paragraphs": [{"inlines": [_t("ㄱ. "), _m("x>0")]}]},
        {"type": "table", "rows": [[[_t("x")], [_m("1")]], [[], [_t("끝")]]]},
    ], "choices": None, "figures": []}
    before = copy.deepcopy(obj)
    assert to_content(obj)["stem"] == [
        {"type": "paragraph", "inlines": [_c("다음 중")]},
        {"type": "box", "title": "<보기>", "paragraphs": [{"inlines": [_c("ㄱ. "), _cm("x>0")]}]},
        {"type": "table", "rows": [[[_c("x")], [_cm("1")]], [[], [_c("끝")]]]},
    ]
    assert obj == before


def test_to_content_fills_missing_box_title():
    obj = {"stem": [{"type": "box", "title": None, "paragraphs": [{"inlines": [_t("ㄱ")]}]}], "choices": None}
    assert to_content(obj)["stem"][0]["title"] == "<보기>"
