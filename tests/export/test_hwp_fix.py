"""'한글에서 직접 고치기' 표시(hwp_fix): 확인 완료를 막지 않고, 내보내면 원본 LaTeX가 눈에 띄는 글자로 들어간다."""
import unittest

from app.api.problem_logic import analyze, check_math
from app.api.schemas_problem import HintOut
from tests.export.test_m2 import M, T, equations, prob, run, section

HOLE = r"\widehat{AB} = \frac{\pi}{2}"            # 아직 변환기가 지원하지 않는 명령(호는 \overparen으로 지원됨)
DOCUMENTED_ONLY = r"p \wedge q"                     # 공식 문서에는 있지만 한글 렌더링 미확인이라 막혀 있다


def doc(*inlines):
    return {"stem": [{"type": "paragraph", "inlines": list(inlines)}], "choices": {"items": [], "layout": "auto"},
            "figures": []}


class Flagged(unittest.TestCase):
    def test_unflagged_unsupported_blocks_confirm_and_names_the_symbol(self):
        _, blockers, _ = analyze(doc(M(HOLE)))
        self.assertEqual([b["code"] for b in blockers], ["MATH_UNSUPPORTED"])
        self.assertIn(r"\widehat", blockers[0]["message"])           # 어떤 기호 때문인지 알려 준다
        self.assertIn("한글에서 수정", blockers[0]["message"])           # 풀 길이 있다는 것도 알려 준다

    def test_documented_symbol_is_named_in_check(self):
        r = check_math(DOCUMENTED_ONLY)
        self.assertEqual(r["status"], "unsupported")
        self.assertIn(r"\wedge", r["message"])

    def test_flagged_does_not_block_and_leaves_a_hint(self):
        hints, blockers, has = analyze(doc(T("그림에서 "), M(HOLE, hwp_fix=True)))
        self.assertEqual(blockers, [])
        self.assertTrue(has)
        self.assertEqual([h["kind"] for h in hints], ["hwp_fix"])
        self.assertTrue(hints[0]["path"])

    def test_response_model_accepts_the_hint_kind(self):
        # HintOut.kind에 hwp_fix가 없으면 '한글에서 수정'을 누른 뒤 저장·불러오기 응답이 검증에서 실패한다(503/500)
        hints, _, _ = analyze(doc(M(HOLE, hwp_fix=True)))
        self.assertEqual(HintOut(**hints[0]).kind, "hwp_fix")

    def test_flagged_empty_math_still_blocks(self):
        _, blockers, _ = analyze(doc(M(" ", hwp_fix=True)))
        self.assertEqual([b["code"] for b in blockers], ["MATH_UNSUPPORTED"])

    def test_export_puts_raw_latex_as_text_and_warns(self):
        r = run([prob([T("값 "), M(HOLE, hwp_fix=True)])])
        self.assertIn("HWP_FIX_FLAGGED", r.report.codes())
        self.assertEqual(len(equations(r)), 0)
        self.assertIn("[한글에서 수식 입력: " + HOLE + "]", section(r))
        self.assertEqual(r.report.status, "warnings")

    def test_flag_overrides_even_a_convertible_formula(self):
        r = run([prob([M(r"x^2", hwp_fix=True)])])
        self.assertEqual(len(equations(r)), 0)
        self.assertIn("HWP_FIX_FLAGGED", r.report.codes())

    def test_unflagged_formula_is_unchanged(self):
        r = run([prob([M(r"x^2")])])
        self.assertEqual(len(equations(r)), 1)
        self.assertNotIn("HWP_FIX_FLAGGED", r.report.codes())


if __name__ == "__main__":
    unittest.main()
