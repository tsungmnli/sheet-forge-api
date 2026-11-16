import io
import re
import unittest
import zipfile

from lxml import etree

from app.export.hwpx import ExportMeta, ExportRequest, export_hwpx
from app.export.hwpx.builders import Equation, build_problem_paragraphs
from app.export.hwpx.layout import plan_layout
from app.export.hwpx.preset import ExportPreset
from app.export.hwpx.report import ExportReport
from app.export.hwpx.validate import validate_package

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
META = ExportMeta("테스트", "2026-11-15T00:00:00Z")
LONG = r"x^2+y^2+6x-20y+1=3x^2-4y^2+5x-6y+7"   # 추정 21em: 1단(약 48em)은 한 줄, 3단(약 15.5em)은 줄바꿈


def prob(inlines, pid="p1"):
    return {"id": pid, "status": "confirmed",
            "content": {"stem": [{"type": "paragraph", "inlines": inlines}]}}


def T(v):
    return {"t": "text", "v": v}


def M(latex, **kw):
    return {"t": "math", "latex": latex, **kw}


def run(problems, preset=None):
    return export_hwpx(ExportRequest(problems, preset, META))


def section(r):
    z = zipfile.ZipFile(io.BytesIO(r.hwpx_bytes))
    return z.read("Contents/section0.xml").decode("utf-8")


def equations(r):
    root = etree.fromstring(section(r).encode("utf-8"))
    return list(root.iter(f"{{{HP}}}equation"))


def script_of(e):
    return e.find(f"{{{HP}}}script").text


class EquationEmission(unittest.TestCase):
    def test_minimal_form_and_text_interleaving(self):
        r = run([prob([T("함수 "), M(r"f(x)=\frac{3x+1}{x+1}"), T("에 대하여 "), M(r"x^2")])])
        eqs = equations(r)
        self.assertEqual(len(eqs), 2)
        e = eqs[0]
        self.assertEqual((e.get("baseLine"), e.find(f"{{{HP}}}sz").get("width"), e.find(f"{{{HP}}}sz").get("height")),
                         ("0", "0", "0"))                                  # [검증 t6a, t6b]
        self.assertEqual(e.get("font"), "HancomEQN")
        self.assertIn("over", script_of(e))
        s = section(r)
        self.assertNotIn("linesegarray", s)                                # [검증 t2]
        # 순서: 글자 → 수식 → 글자 → 수식 → 빈 <hp:t/>
        order = re.findall(r"<hp:t>([^<]*)</hp:t>|<hp:equation |<hp:t/>", s)
        self.assertTrue(s.index("함수 ") < s.index("<hp:equation") < s.index("에 대하여 "))
        self.assertTrue(s.rstrip().endswith("</hp:equation><hp:t/></hp:run></hp:p></hs:sec>")
                        or "</hp:equation><hp:t/></hp:run></hp:p>" in s)
        self.assertEqual(r.report.stats["equations"], 2)
        self.assertEqual(validate_package(r.hwpx_bytes), [])

    def test_base_unit_follows_font_size(self):
        r10 = run([prob([M("x")])])
        r12 = run([prob([M("x")])], {"typography": {"font_size_pt": 12}})
        self.assertEqual(equations(r10)[0].get("baseUnit"), "1000")        # [검증 t17a]
        self.assertEqual(equations(r12)[0].get("baseUnit"), "1200")

    def test_script_is_xml_escaped(self):
        r = run([prob([M(r"a<b>c")])])
        self.assertIn("&lt;", section(r))
        self.assertEqual(re.sub(r"\s", "", script_of(equations(r)[0])), "a<b>c")
        self.assertEqual(validate_package(r.hwpx_bytes), [])

    def test_ids_unique_and_deterministic(self):
        probs = [prob([M("x"), T(" "), M("y")], pid=f"p{i}") for i in range(5)]
        a, b = run(probs), run(probs)
        self.assertEqual(a.hwpx_bytes, b.hwpx_bytes)
        ids = [e.get("id") for e in equations(a)]
        zs = [e.get("zOrder") for e in equations(a)]
        self.assertEqual(len(ids), 10)
        self.assertEqual(len(set(ids)), 10)
        self.assertEqual(len(set(zs)), 10)

    def test_adjacent_equations_each_get_trailing_empty_t(self):
        r = run([prob([M("a"), M("b")])])
        self.assertEqual(section(r).count("</hp:equation><hp:t/>"), 2)

    def test_text_only_paragraph_unchanged(self):
        r = run([prob([T("글자만")])])
        self.assertEqual(r.report.stats["equations"], 0)
        self.assertIn("<hp:t>글자만</hp:t>", section(r))


class WrapByColumnWidth(unittest.TestCase):
    def test_one_column_no_wrap_three_columns_wrap(self):
        p = prob([T("다음 식을 정리하시오. "), M(LONG)])
        r1 = run([p])
        r3 = run([p], {"columns": {"count": 3}})
        self.assertNotIn("#", script_of(equations(r1)[0]))
        self.assertIn("#", script_of(equations(r3)[0]))
        self.assertIn("EQ_AUTO_BROKEN", r3.report.codes())
        self.assertNotIn("EQ_AUTO_BROKEN", r1.report.codes())
        self.assertEqual(r3.report.stats["equations_wrapped"], 1)
        self.assertEqual(validate_package(r3.hwpx_bytes), [])

    def test_limit_is_90_percent_of_column_width(self):
        lc = plan_layout(ExportPreset.from_dict({"columns": {"count": 3}}))
        specs = build_problem_paragraphs(prob([M(LONG)]), "01", ExportReport(), lc)
        eq = [p for p in specs[1].parts if isinstance(p, Equation)][0]
        self.assertTrue(eq.wrapped)
        from app.export.math.convert import convert
        res = convert(LONG, max_width_em=0.9 * lc.col_w / lc.font_hwp)
        self.assertEqual(eq.script, res.script)
        self.assertTrue(all(w * lc.font_hwp <= 0.9 * lc.col_w for w in res.line_widths_em))

    def test_larger_font_wraps_earlier(self):
        p = prob([M(LONG)])
        small = run([p], {"columns": {"count": 2}, "typography": {"font_size_pt": 9}})
        big = run([p], {"columns": {"count": 2}, "typography": {"font_size_pt": 14}})
        n = lambda r: script_of(equations(r)[0]).count("#")
        self.assertLessEqual(n(small), n(big))

    def test_too_wide_is_reported_not_raised(self):
        p = prob([M(r"\frac{aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa+bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb}{c}")])
        r = run([p], {"columns": {"count": 3}})
        self.assertIn("EQ_TOO_WIDE", r.report.codes())
        self.assertEqual(len(equations(r)), 1)

    def test_user_breaks_take_priority_and_are_not_reported_as_auto(self):
        p = prob([M(LONG, breaks=[2])])
        r = run([p], {"columns": {"count": 3}})
        self.assertEqual(script_of(equations(r)[0]).count("#"), 1)
        self.assertNotIn("EQ_AUTO_BROKEN", r.report.codes())
        r1 = run([p])                                                       # 1단이어도 사용자 지정은 그대로
        self.assertEqual(script_of(equations(r1)[0]).count("#"), 1)

    def test_cases_hash_is_not_counted_as_wrapped(self):
        r = run([prob([M(r"\begin{cases}a\\b\end{cases}")])])
        self.assertIn("#", script_of(equations(r)[0]))
        self.assertEqual(r.report.stats["equations_wrapped"], 0)


class FallbackAndNotes(unittest.TestCase):
    def test_failed_conversion_falls_back_to_text(self):
        r = run([prob([T("값 "), M(r"\foo{x}")])])
        self.assertIn("UNSUPPORTED_MATH", r.report.codes())
        self.assertEqual(len(equations(r)), 0)
        self.assertIn(r"[수식 오류: \foo{x}]", section(r))
        self.assertEqual(validate_package(r.hwpx_bytes), [])

    def test_unverified_vocabulary_is_gated(self):
        r = run([prob([M(r"a\approx b")])])
        self.assertIn("UNSUPPORTED_MATH", r.report.codes())
        self.assertEqual(len(equations(r)), 0)

    def test_report_where_points_to_inline(self):
        r = run([prob([T("a"), M(r"\foo")], pid="px")])
        item = [i for i in r.report.items if i.code == "UNSUPPORTED_MATH"][0]
        self.assertEqual((item.problem_id, item.where), ("px", "stem[0].inline[1]"))

    def test_converter_warnings_become_info_notes(self):
        r = run([prob([M(r"\text{가나}+1")])])
        notes = [i for i in r.report.items if i.code == "MATH_NOTE"]
        self.assertTrue(notes and notes[0].severity == "info")
        self.assertEqual(len(equations(r)), 1)

    def test_size_mode_estimated_is_reported_as_not_implemented(self):
        r = run([prob([M("x")])], {"equation": {"size_mode": "estimated"}})
        self.assertIn("NOT_IMPLEMENTED", r.report.codes())
        self.assertEqual(equations(r)[0].find(f"{{{HP}}}sz").get("width"), "0")


class ValidatorCatchesBadEquations(unittest.TestCase):
    def mutate(self, fn):
        r = run([prob([M("x"), M("y")])])
        zin = zipfile.ZipFile(io.BytesIO(r.hwpx_bytes))
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as zo:
            for i in zin.infolist():
                data = zin.read(i.filename)
                if i.filename == "Contents/section0.xml":
                    data = fn(data.decode("utf-8")).encode("utf-8")
                zo.writestr(i, data, compress_type=i.compress_type)
        return validate_package(out.getvalue())

    def test_duplicate_id(self):
        ids = []
        def dup(s):
            ids.extend(re.findall(r'<hp:equation id="(\d+)"', s))
            return s.replace(f'id="{ids[1]}"', f'id="{ids[0]}"', 1)
        self.assertTrue(any("수식 id 중복" in p for p in self.mutate(dup)))

    def test_nonzero_size_is_rejected(self):
        bad = lambda s: s.replace('<hp:sz width="0"', '<hp:sz width="500"', 1)
        self.assertTrue(any("sz·baseLine" in p for p in self.mutate(bad)))

    def test_empty_script(self):
        bad = lambda s: re.sub(r"<hp:script>[^<]*</hp:script>", "<hp:script></hp:script>", s, count=1)
        self.assertTrue(any("스크립트가 비어" in p for p in self.mutate(bad)))


if __name__ == "__main__":
    unittest.main()
