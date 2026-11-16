import io
import re
import unittest
import zipfile

from app.export.hwpx import ExportMeta, ExportRequest, export_hwpx
from app.export.hwpx.builders import TAB, build_problem_paragraphs, choose_cols
from app.export.hwpx.report import ExportReport
from app.export.hwpx.validate import validate_package

META = ExportMeta("테스트", "2026-11-15T00:00:00Z")
T = lambda v: {"t": "text", "v": v}
M = lambda latex: {"t": "math", "latex": latex}


def prob(items, pid="p1"):
    return {"id": pid, "status": "confirmed",
            "content": {"stem": [{"type": "paragraph", "inlines": [T("값은?")]}],
                        "choices": {"items": items, "layout": "auto"}}}


def run(items, preset=None):
    return export_hwpx(ExportRequest([prob(items)], preset, META))


def xml(r, name):
    return zipfile.ZipFile(io.BytesIO(r.hwpx_bytes)).read(name).decode("utf-8")


SHORT = [[T(str(k))] for k in range(1, 6)]
LONGTXT = [[T("가나다라마바사아자차카타파하" * 2)] for _ in range(5)]


class ChooseCols(unittest.TestCase):
    def test_order_and_limits(self):
        self.assertEqual(choose_cols([2000] * 5, 53858, 0.1), 5)
        self.assertEqual(choose_cols([10000] * 5, 53858, 0.1), 3)   # 11000 > 5열 칸 10771, ≤ 3열 칸 17952
        self.assertEqual(choose_cols([20000] * 5, 53858, 0.1), 2)
        self.assertEqual(choose_cols([40000] * 5, 53858, 0.1), 1)
        self.assertEqual(choose_cols([2000] * 2, 53858, 0.1), 2)    # 선택지 수 이하
        self.assertEqual(choose_cols([2000] * 4, 53858, 0.1), 4)
        self.assertEqual(choose_cols([20000] * 4, 53858, 0.1), 2)   # 3+1이 되지 않게


class Rows(unittest.TestCase):
    def test_short_choices_one_row_with_tabs_and_markers(self):
        specs = build_problem_paragraphs(prob(SHORT), "01", ExportReport(), None)
        rows = [s for s in specs if s.role == "choice"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].tab_cols, 5)
        self.assertEqual(rows[0].parts.count(TAB), 4)
        self.assertEqual(rows[0].text[:3], "① 1")
        self.assertFalse(rows[0].keep_with_next)              # 문항의 마지막 문단

    def test_three_plus_two_rows_keep_flags(self):
        r = run(LONGTXT, {"columns": {"count": 1}})
        self.assertIn(r.report.stats["choice_rows"], (2, 3, 5))
        r = run([[T("가" * 8)] for _ in range(5)], {"columns": {"count": 2}})  # 칸이 좁아 여러 행
        self.assertGreaterEqual(r.report.stats["choice_rows"], 2)
        self.assertEqual(validate_package(r.hwpx_bytes), [])

    def test_tab_xml_and_tabpr(self):
        r = run(SHORT)
        sec, head = xml(r, "Contents/section0.xml"), xml(r, "Contents/header.xml")
        self.assertIn('<hp:t>① 1<hp:tab width="0" leader="0" type="1"/>② 2', sec)
        m = re.search(r'<hh:tabPr id="3" autoTabLeft="0" autoTabRight="0">(.*?)</hh:tabPr>', head)
        self.assertEqual(len(re.findall("<hh:tabItem", m.group(1))), 4)
        self.assertIn('<hh:tabProperties itemCnt="4">', head)
        self.assertIn('tabPrIDRef="3"', head)
        self.assertEqual(validate_package(r.hwpx_bytes), [])

    def test_equation_choices(self):
        r = run([[M(r"\frac{1}{2}")], [M(r"\sqrt{3}")], [M("x^2")], [M("2x")], [M("5")]])
        sec = xml(r, "Contents/section0.xml")
        self.assertEqual(sec.count("<hp:equation"), 5)
        self.assertEqual(validate_package(r.hwpx_bytes), [])

    def test_near_limit_reported_and_deterministic(self):
        a = run(LONGTXT, {"columns": {"count": 3}})
        self.assertIn("CHOICES_NEAR_LIMIT", a.report.codes())
        self.assertEqual(a.hwpx_bytes, run(LONGTXT, {"columns": {"count": 3}}).hwpx_bytes)


if __name__ == "__main__":
    unittest.main()
