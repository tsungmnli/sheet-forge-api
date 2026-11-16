"""B5-4a: 확인 시 고친 조각 수. DB 없이 도는 단위 테스트."""
import copy
import inspect
import unittest

from app.api import problem_service
from app.api.edit_stats import count_edits


def _t(v):
    return {"t": "text", "v": v, "latex": None}


def _m(s):
    return {"t": "math", "v": None, "latex": s}


REC = {
    "stem": [{"inlines": [_t("함수 "), _m("f(x)"), _t("의 값은?")]}],
    "choices": {"items": [[_m("1")], [_m("2")]], "layout": "auto"},
}


class CountEditsTest(unittest.TestCase):
    def test_no_change(self):
        r = count_edits(REC, copy.deepcopy(REC))
        self.assertEqual(r["edited"], {"text": 0, "math": 0, "choices": 0, "paragraphs": 0})
        self.assertEqual(r["of"], {"text": 2, "math": 1, "choices": 2, "paragraphs": 0})

    def test_whitespace_only_is_not_an_edit(self):
        c = copy.deepcopy(REC)
        c["stem"][0]["inlines"][0]["v"] = "함수  "
        self.assertEqual(count_edits(REC, c)["edited"]["text"], 0)

    def test_math_edit(self):
        c = copy.deepcopy(REC)
        c["stem"][0]["inlines"][1]["latex"] = "g(x)"
        e = count_edits(REC, c)["edited"]
        self.assertEqual((e["math"], e["text"], e["choices"]), (1, 0, 0))

    def test_text_edit(self):
        c = copy.deepcopy(REC)
        c["stem"][0]["inlines"][2]["v"] = "의 값을 구하시오."
        e = count_edits(REC, c)["edited"]
        self.assertEqual((e["text"], e["math"]), (1, 0))

    def test_choice_edit(self):
        c = copy.deepcopy(REC)
        c["choices"]["items"][1] = [_m("3")]
        e = count_edits(REC, c)["edited"]
        self.assertEqual((e["choices"], e["math"]), (1, 0))

    def test_paragraph_merge(self):
        rec = {"stem": [{"inlines": [_t("가")]}, {"inlines": [_t("나")]}], "choices": None}
        c = {"stem": [{"inlines": [_t("가"), _t("나")]}], "choices": None}
        r = count_edits(rec, c)
        self.assertEqual(r["edited"]["paragraphs"], 1)
        self.assertEqual(r["of"]["paragraphs"], 1)

    def test_added_piece_and_figures_ignored(self):
        c = copy.deepcopy(REC)
        c["stem"][0]["inlines"].append(_m("x"))
        c["figures"] = [{"id": "fig_1"}]
        e = count_edits(REC, c)["edited"]
        self.assertEqual(e["math"], 1)

    def test_result_has_numbers_only(self):
        r = count_edits(REC, REC)
        self.assertTrue(all(isinstance(v, int) for d in r.values() for v in d.values()))


class WiringTest(unittest.TestCase):
    def test_confirm_records_edits_before_status_change(self):
        src = inspect.getsource(problem_service.confirm)
        self.assertLess(src.index("count_edits("), src.index('p.status = "confirmed"'))
        self.assertIn("recognized is not None", src)


if __name__ == "__main__":
    unittest.main()
