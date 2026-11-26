"""기하 기호(호·선분·직선·반직선·평행·수직·각): sample.hwpx에서 한글 표기를 확인했다.

arch{rm AB} 호 · bar{rm AB} 선분 · dyad{rm AB} 직선 · vec{rm AB} 반직선 · ⫽ 평행 · BOT 수직 · ANGLE 각
"""
import unittest

from app.api.problem_logic import analyze
from app.export.math.convert import convert
from tests.export.test_m2 import M


def script(latex):
    r = convert(latex)
    assert r.ok, r.error
    return r.script


def doc(*inlines):
    return {"stem": [{"type": "paragraph", "inlines": list(inlines)}], "choices": {"items": [], "layout": "auto"},
            "figures": []}


class Geometry(unittest.TestCase):
    def test_arc(self):
        self.assertTrue(script(r"\overparen{\mathrm{AB}}").startswith("arch {"))

    def test_arc_aliases(self):
        for cmd in (r"\overgroup", r"\wideparen"):
            self.assertTrue(script(cmd + r"{\mathrm{AB}}").startswith("arch {"), cmd)

    def test_segment_ray_line(self):
        self.assertTrue(script(r"\overline{\mathrm{AB}}").startswith("bar {"))
        self.assertTrue(script(r"\overrightarrow{\mathrm{AB}}").startswith("vec {"))
        self.assertTrue(script(r"\vec{\mathrm{AB}}").startswith("vec {"))
        self.assertTrue(script(r"\overleftrightarrow{\mathrm{AB}}").startswith("dyad {"))

    def test_parallel_uses_the_verified_glyph(self):
        s = script(r"\overline{\mathrm{AB}} \parallel \overline{\mathrm{CD}}")
        self.assertIn("\u2afd", s)
        self.assertNotIn("VERT", s)

    def test_perpendicular(self):
        s = script(r"\overline{\mathrm{AB}} \perp \overline{\mathrm{CD}}")
        self.assertIn(" BOT ", s)

    def test_unicode_symbols_from_ocr(self):
        self.assertIn("\u2afd", script("\\overline{AB} \u2225 \\overline{CD}"))
        self.assertIn("\u2afd", script("\\overline{AB} \u2afd \\overline{CD}"))
        self.assertIn(" BOT ", script("\\overline{AB} \u22a5 \\overline{CD}"))

    def test_widehat_is_still_blocked(self):
        # 각 위의 모자와 호가 섞여 쓰이므로, 한글 표기를 확인하기 전에는 풀지 않는다
        self.assertFalse(convert(r"\widehat{AB}").ok)


class StaleFlag(unittest.TestCase):
    def test_flag_on_a_convertible_formula_says_it_can_be_unflagged(self):
        hints, blockers, _ = analyze(doc(M(r"\overparen{\mathrm{AB}}", hwp_fix=True)))
        self.assertEqual(blockers, [])
        self.assertEqual([h["kind"] for h in hints], ["hwp_fix"])
        self.assertIn("풀면", hints[0]["message"])

    def test_flag_on_a_still_unsupported_formula_keeps_the_original_message(self):
        hints, _, _ = analyze(doc(M(r"\widehat{AB}", hwp_fix=True)))
        self.assertNotIn("풀면", hints[0]["message"])


if __name__ == "__main__":
    unittest.main()
