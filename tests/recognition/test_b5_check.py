"""B5-3b-2: 수식 변환기 점검. 변환기는 가짜로 바꿔 끼워 시험하고, 실제 변환기는 결정이 분명한 입력만 쓴다."""
import copy
import unittest
from types import SimpleNamespace as NS

from app.recognition.llm.check import check_math


def T(v):
    return {"t": "text", "v": v, "latex": None}


def M(s):
    return {"t": "math", "v": None, "latex": s}


def fake(latex):
    if latex == "BAD":
        return NS(ok=False, error="모름", error_pos=2, warnings=[])
    if latex == "WARN":
        return NS(ok=True, error=None, error_pos=None, warnings=["주의"])
    if latex == "BOOM":
        raise RuntimeError("x")
    return NS(ok=True, error=None, error_pos=None, warnings=[])


class CheckTest(unittest.TestCase):
    def test_positions_and_kinds(self):
        obj = {"stem": [{"inlines": [T("a"), M("ok")]}, {"inlines": [M("BAD"), M("WARN")]}],
               "choices": [{"inlines": [M("BOOM")]}]}
        r = check_math(obj, fake)
        self.assertEqual([(f["area"], f["para"], f["inline"], f["latex"], f["error"], f["error_pos"]) for f in r.failures],
                         [("stem", 1, 0, "BAD", "모름", 2), ("choices", 0, 0, "BOOM", "internal", None)])
        self.assertEqual([(w["area"], w["para"], w["inline"], w["warnings"]) for w in r.warnings],
                         [("stem", 1, 1, ["주의"])])

    def test_no_math_and_none_choices(self):
        r = check_math({"stem": [{"inlines": [T("글")]}], "choices": None}, fake)
        self.assertEqual((r.failures, r.warnings), ([], []))

    def test_input_untouched(self):
        obj = {"stem": [{"inlines": [M("BAD")]}], "choices": None}
        before = copy.deepcopy(obj)
        check_math(obj, fake)
        self.assertEqual(obj, before)

    def test_real_converter_empty_fails_and_simple_passes(self):
        r = check_math({"stem": [{"inlines": [M("x"), M("  ")]}], "choices": None})
        self.assertEqual([(f["para"], f["inline"]) for f in r.failures], [(0, 1)])


if __name__ == "__main__":
    unittest.main()
