"""B5-3b-1: 읽기 결과 -> content 계약."""
import copy
import unittest

from app.recognition.llm.content import to_content


def T(v):
    return {"t": "text", "v": v, "latex": None}


def M(s):
    return {"t": "math", "v": None, "latex": s}


class ToContentTest(unittest.TestCase):
    def test_stem_gets_type_and_nulls_removed(self):
        obj = {"stem": [{"inlines": [T("함수 "), M("f(x)"), T("의 값은?")]}], "choices": None}
        out = to_content(obj)
        self.assertEqual(out["stem"], [{"type": "paragraph", "inlines": [
            {"t": "text", "v": "함수 "}, {"t": "math", "latex": "f(x)"}, {"t": "text", "v": "의 값은?"}]}])

    def test_choices_become_items(self):
        obj = {"stem": [], "choices": [{"inlines": [M("1")]}, {"inlines": [T("가"), M("x")]}]}
        out = to_content(obj)
        self.assertEqual(out["choices"], {"items": [[{"t": "math", "latex": "1"}],
                                                    [{"t": "text", "v": "가"}, {"t": "math", "latex": "x"}]],
                                          "layout": "auto"})

    def test_no_choices_is_none(self):
        self.assertIsNone(to_content({"stem": [], "choices": None})["choices"])
        self.assertIsNone(to_content({"stem": [], "choices": []})["choices"])

    def test_figures_empty_and_input_untouched(self):
        obj = {"stem": [{"inlines": [T("a")]}], "choices": [{"inlines": [M("1")]}],
               "figures": [{"box_2d": [0, 0, 10, 10], "placement": "after_stem"}]}
        before = copy.deepcopy(obj)
        self.assertEqual(to_content(obj)["figures"], [])
        self.assertEqual(obj, before)


if __name__ == "__main__":
    unittest.main()
