"""표: 열 폭 분배·행 높이 + 내보내기(실선 borderFill 추가, 행·열 수, 단 수별 폭)."""
import io
import unittest
import zipfile

from lxml import etree

from app.export.hwpx import ExportMeta, ExportRequest, export_hwpx
from app.export.hwpx import box_geometry as bg
from app.export.hwpx.validate import HH, HP, validate_package

META = ExportMeta("테스트", "2026-11-18T00:00:00Z")


def t(v):
    return {"t": "text", "v": v}


def m(latex):
    return {"t": "math", "latex": latex}


def table_problem():
    rows = [[[t("사용 시간(시간)")], [t("학생 수(명)")], [t("상대도수")]],
            [[t("0 이상 ~ 2 미만")], [m("6")], []],
            [[t("2 ~ 4")], [m("B")], [m("0.24")]],
            [[t("4 ~ 6")], [m("45")], [m("0.3")]],
            [[t("합계")], [], [m("1")]]]
    return {"id": "p1", "status": "confirmed", "content": {
        "stem": [{"type": "paragraph", "inlines": [t("표를 보고 답하시오.")]},
                 {"type": "table", "rows": rows}]}}


def run(problem, cols=2):
    return export_hwpx(ExportRequest([problem], {"columns": {"count": cols, "gap_mm": None}}, META))


def parts(r):
    z = zipfile.ZipFile(io.BytesIO(r.hwpx_bytes))
    return etree.fromstring(z.read("Contents/section0.xml")), etree.fromstring(z.read("Contents/header.xml"))


class Geometry(unittest.TestCase):
    def test_widths_sum_exact_and_proportional(self):
        w = bg.split_widths([9.0, 5.0, 4.0], 24661)
        self.assertEqual(sum(w), 24661)
        self.assertGreater(w[0], w[1])
        self.assertGreater(w[1], w[2])

    def test_min_weight(self):
        w = bg.split_widths([0.0, 10.0], 10000)
        self.assertGreater(w[0], 0)
        self.assertEqual(sum(w), 10000)

    def test_row_height_min_and_growth(self):
        self.assertEqual(bg.row_height([(3.0, 0, False)], [8000], 1000, 160), 1850)   # 샘플 행 높이
        tall = bg.row_height([(30.0, 0, False)], [4000], 1000, 160)                  # 여러 줄로 감김
        self.assertGreater(tall, 1850)

    def test_table_width_matches_sample(self):
        self.assertEqual(bg.table_width(25795), 24661)


class Export(unittest.TestCase):
    def test_valid_and_structure(self):
        r = run(table_problem())
        self.assertEqual(validate_package(r.hwpx_bytes), [])
        sec, head = parts(r)
        tbl = next(sec.iter(f"{{{HP}}}tbl"))
        self.assertEqual((tbl.get("rowCnt"), tbl.get("colCnt")), ("5", "3"))
        self.assertEqual(len(tbl.findall(f"{{{HP}}}tr")), 5)
        self.assertEqual(int(tbl.find(f"{{{HP}}}sz").get("width")), r.layout["col_w"] - bg.TABLE_SIDE_TRIM)
        self.assertEqual(r.report.stats["tables"], 1)
        texts = ["".join(x.itertext()) for x in tbl.iter(f"{{{HP}}}tc")]
        self.assertIn("사용 시간(시간)", "".join(texts))
        self.assertEqual(len(list(tbl.iter(f"{{{HP}}}equation"))), 6)

    def test_border_fill_added_once_and_referenced(self):
        r = run(table_problem())
        sec, head = parts(r)
        bfs = list(head.iter(f"{{{HH}}}borderFill"))
        solid = [b for b in bfs if b.find(f"{{{HH}}}leftBorder").get("type") == "SOLID"]
        self.assertEqual(len(solid), 1)
        self.assertEqual(next(sec.iter(f"{{{HP}}}tbl")).get("borderFillIDRef"), solid[0].get("id"))
        # 표가 둘이어도 borderFill은 하나
        two = {"id": "p2", "status": "confirmed", "content": table_problem()["content"]}
        r2 = export_hwpx(ExportRequest([table_problem(), two], {"columns": {"count": 2, "gap_mm": None}}, META))
        self.assertEqual(validate_package(r2.hwpx_bytes), [])
        _, head2 = parts(r2)
        self.assertEqual(len([b for b in head2.iter(f"{{{HH}}}borderFill")
                              if b.find(f"{{{HH}}}leftBorder").get("type") == "SOLID"]), 1)

    def test_no_table_no_border_change(self):
        p = {"id": "p", "status": "confirmed", "content": {"stem": [{"type": "paragraph", "inlines": [t("가나다")]}]}}
        _, head = parts(run(p))
        self.assertEqual(len(list(head.iter(f"{{{HH}}}borderFill"))), 2)

    def test_columns_1_2_3(self):
        for cols in (1, 2, 3):
            r = run(table_problem(), cols)
            self.assertEqual(validate_package(r.hwpx_bytes), [])
            sec, _ = parts(r)
            tbl = next(sec.iter(f"{{{HP}}}tbl"))
            self.assertEqual(int(tbl.find(f"{{{HP}}}sz").get("width")), r.layout["col_w"] - bg.TABLE_SIDE_TRIM)

    def test_ragged_rows_padded_and_empty_skipped(self):
        p = table_problem()
        p["content"]["stem"][1]["rows"] = [[[t("a")], [t("b")], [t("c")]], [[t("d")]]]
        r = run(p)
        self.assertEqual(validate_package(r.hwpx_bytes), [])
        sec, _ = parts(r)
        self.assertEqual([len(tr.findall(f"{{{HP}}}tc")) for tr in sec.iter(f"{{{HP}}}tr")], [3, 3])
        p["content"]["stem"][1]["rows"] = []
        r = run(p)
        self.assertEqual(r.report.stats["tables"], 0)
        self.assertIn("TABLE_EMPTY", r.report.codes())

    def test_deterministic_and_box_plus_table(self):
        self.assertEqual(run(table_problem()).hwpx_bytes, run(table_problem()).hwpx_bytes)
        p = table_problem()
        p["content"]["stem"].append({"type": "box", "title": "<보기>", "paragraphs": [{"inlines": [t("ㄱ. 가")]}]})
        r = run(p)
        self.assertEqual(validate_package(r.hwpx_bytes), [])
        self.assertEqual((r.report.stats["tables"], r.report.stats["boxes"]), (1, 1))


if __name__ == "__main__":
    unittest.main()
