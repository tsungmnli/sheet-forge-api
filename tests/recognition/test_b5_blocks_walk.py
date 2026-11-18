"""B5-5b: box·table이 섞인 읽기 결과를 repair·check·math_repair·recognizer가 다루는지 (LLM 호출 없음)."""
import json

from app.recognition.llm.blocks import inline_at, iter_inlines
from app.recognition.llm.check import check_math
from app.recognition.llm.math_repair import repair_math
from app.recognition.llm.recognizer import _is_empty
from app.recognition.llm.repair import normalize_read


def _t(v):
    return {"t": "text", "v": v, "latex": None}


def _m(latex):
    return {"t": "math", "v": None, "latex": latex}


def _obj():
    return {
        "stem": [
            {"inlines": [_t("다음 중")]},
            {"type": "box", "title": "<보기>",
             "paragraphs": [{"inlines": [_t("ㄱ. "), _m("x>0")]}, {"inlines": [_t("ㄴ. "), _m("BAD")]}]},
            {"type": "table", "rows": [[[_t("x")], [_m("1")]], [[_m("BAD2")], []]]},
        ],
        "choices": [{"inlines": [_m("3")]}],
    }


class _R:
    def __init__(self, ok):
        self.ok, self.error, self.error_pos, self.warnings = ok, "e", 0, []


def _conv(latex):
    return _R(not latex.startswith("BAD"))


class _Res:
    def __init__(self, text):
        self.text = text


class _Client:
    def __init__(self, text):
        self.text = text

    def generate(self, model, image, prompt, schema, limits):
        return _Res(self.text)


def test_iter_inlines_positions():
    pos = [p for p, _, _ in iter_inlines(_obj())]
    assert pos == [
        {"area": "stem", "para": 0},
        {"area": "stem", "para": 1, "p": 0},
        {"area": "stem", "para": 1, "p": 1},
        {"area": "stem", "para": 2, "r": 0, "c": 0},
        {"area": "stem", "para": 2, "r": 0, "c": 1},
        {"area": "stem", "para": 2, "r": 1, "c": 0},
        {"area": "stem", "para": 2, "r": 1, "c": 1},
        {"area": "choices", "para": 0},
    ]


def test_check_math_reports_block_positions():
    chk = check_math(_obj(), _conv)
    keys = ("area", "para", "p", "r", "c", "inline")
    assert [{k: f[k] for k in keys if k in f} for f in chk.failures] == [
        {"area": "stem", "para": 1, "p": 1, "inline": 1},
        {"area": "stem", "para": 2, "r": 1, "c": 0, "inline": 0},
    ]


def test_normalize_read_fixes_pieces_inside_box_and_table():
    obj = {"stem": [{"type": "box", "title": None, "paragraphs": [{"inlines": [_t("점 A")]}]},
                    {"type": "table", "rows": [[[_t("B")]]]}], "choices": None}
    n = normalize_read(obj)
    assert obj["stem"][0]["paragraphs"][0]["inlines"] == [_t("점 "), _m("A")]
    assert obj["stem"][1]["rows"][0][0] == [_m("B")]
    assert n == 2


def test_merge_paragraphs_skips_blocks_and_merges_inside_box():
    obj = {"stem": [{"inlines": [_t("다음 중 옳은")]},
                    {"type": "box", "title": None,
                     "paragraphs": [{"inlines": [_t("ㄱ. 유리수는")]}, {"inlines": [_t("정수이다.")]}]},
                    {"inlines": [_t("것은")]}], "choices": None}
    normalize_read(obj)
    assert len(obj["stem"]) == 3
    assert [p["inlines"] for p in obj["stem"][1]["paragraphs"]] == [[_t("ㄱ. 유리수는 정수이다.")]]


def test_repair_math_writes_back_to_box_and_table_cells():
    obj = _obj()
    chk = check_math(obj, _conv)
    client = _Client(json.dumps({"fixes": [{"id": 0, "latex": "y"}, {"id": 1, "latex": "z"}]}))
    out = repair_math(client, "m", obj, chk.failures, convert_fn=_conv)
    assert out.fixed == 2
    assert inline_at(out.obj, chk.failures[0])["latex"] == "y"
    assert inline_at(out.obj, chk.failures[1])["latex"] == "z"
    assert inline_at(obj, chk.failures[0])["latex"] == "BAD"   # 입력은 그대로


def test_is_empty_looks_into_blocks():
    assert _is_empty({"stem": [{"type": "table", "rows": [[[_t(" ")]]]}], "choices": None})
    assert not _is_empty({"stem": [{"type": "box", "title": None, "paragraphs": [{"inlines": [_t("ㄱ")]}]}],
                          "choices": None})
