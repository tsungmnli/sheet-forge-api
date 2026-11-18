"""<보기> 상자: 기하 계산(샘플 시험지.hwpx 값 재현) + 내보내기 + 단 수별 폭·제목 가운데."""
import io
import re
import unittest
import zipfile

from lxml import etree

from app.export.hwpx import ExportMeta, ExportRequest, export_hwpx
from app.export.hwpx import box_geometry as bg
from app.export.hwpx.validate import HP, validate_package

META = ExportMeta("테스트", "2026-11-18T00:00:00Z")


def line(*inl):
    return {"inlines": list(inl)}


def t(v):
    return {"t": "text", "v": v}


def m(latex):
    return {"t": "math", "latex": latex}


def box_problem(n_lines=4):
    lines = [line(t(f"{k}. "), m(r"\overline{AB}=\overline{DE}"), t(", "), m(r"\angle B=\angle E")) for k in "ㄱㄴㄷㄹ"[:n_lines]]
    return {"id": "p1", "status": "confirmed", "content": {
        "stem": [{"type": "paragraph", "inlines": [t("다음 중 옳은 것은?")]},
                 {"type": "box", "title": "<보기>", "paragraphs": lines}],
        "choices": {"items": [[t("ㄱ, ㄴ")], [t("ㄱ, ㄷ")]]}}}


def run(problem, cols=2):
    return export_hwpx(ExportRequest([problem], {"columns": {"count": cols, "gap_mm": None}}, META))


def section(r):
    z = zipfile.ZipFile(io.BytesIO(r.hwpx_bytes))
    return etree.fromstring(z.read("Contents/section0.xml"))


class SampleGeometry(unittest.TestCase):
    def test_reproduces_sample_numbers(self):
        # 샘플: 2단 한 단 폭 25795, 글자 1000, 줄 간격 160%, 수식 든 줄 4개
        g = bg.plan_box(25795, "<보기>", [(1, True)] * 4, 1000, 160)
        self.assertEqual(g.width, 25585)
        self.assertEqual((g.title_w, g.title_h), (5124, 1865))
        self.assertEqual(g.title_x, 10230)          # 가로 가운데
        self.assertEqual(g.body_y, 932)             # 제목 높이의 절반 = 세로 가운데가 윗선
        self.assertAlmostEqual(g.body_h, 8504, delta=100)   # 샘플은 사람이 정한 값이라 근사

    def test_first_line_clears_title(self):
        g = bg.plan_box(25795, "<보기>", [(1, False)], 1000, 160)
        inset = (g.body_h - 1000) // 2              # 글줄 위쪽 여유(가운데 정렬 가정)
        self.assertGreaterEqual(inset, g.title_h // 2)

    def test_title_spaced(self):
        self.assertEqual(bg.display_title("<보기>"), "< 보 기 >")
        self.assertEqual(bg.display_title("< 보 기 >"), "< 보 기 >")
        self.assertEqual(bg.display_title("조건"), "조건")


class Export(unittest.TestCase):
    def test_valid_package_and_structure(self):
        r = run(box_problem())
        self.assertEqual(validate_package(r.hwpx_bytes), [])
        sec = section(r)
        cont = list(sec.iter(f"{{{HP}}}container"))
        self.assertEqual(len(cont), 1)
        rects = cont[0].findall(f"{{{HP}}}rect")
        self.assertEqual(len(rects), 2)
        pos = cont[0].find(f"{{{HP}}}pos")
        self.assertEqual((pos.get("treatAsChar"), pos.get("vertRelTo")), ("1", "PARA"))
        self.assertEqual(r.report.stats["boxes"], 1)
        texts = [x.text for x in rects[1].iter(f"{{{HP}}}t")]
        self.assertIn("< 보 기 >", texts)
        self.assertEqual(len(list(rects[0].iter(f"{{{HP}}}equation"))), 8)

    def test_width_follows_columns_and_title_centered(self):
        for cols in (1, 2, 3):
            r = run(box_problem(), cols)
            self.assertEqual(validate_package(r.hwpx_bytes), [])
            c = next(section(r).iter(f"{{{HP}}}container"))
            w = int(c.find(f"{{{HP}}}sz").get("width"))
            self.assertEqual(w, r.layout["col_w"] - bg.BOX_WIDTH_TRIM)
            body, title = c.findall(f"{{{HP}}}rect")
            tx = int(title.find(f"{{{HP}}}offset").get("x"))
            tw = round(float(title.find(f"{{{HP}}}rotationInfo").get("centerX")) * 2)
            self.assertAlmostEqual(tx + tw / 2, w / 2, delta=1)       # 가로 가운데
            ty_center = int(title.find(f"{{{HP}}}rotationInfo").get("centerY"))
            body_y = int(body.find(f"{{{HP}}}offset").get("y"))
            self.assertAlmostEqual(ty_center, body_y, delta=1)         # 세로 가운데 = 본문 윗선

    def test_deterministic_and_unique_ids(self):
        a, b = run(box_problem()), run(box_problem())
        self.assertEqual(a.hwpx_bytes, b.hwpx_bytes)
        two = {"id": "p2", "status": "confirmed", "content": box_problem()["content"]}
        r = export_hwpx(ExportRequest([box_problem(), two], {"columns": {"count": 2, "gap_mm": None}}, META))
        self.assertEqual(validate_package(r.hwpx_bytes), [])
        ids = re.findall(r'<hp:container id="(\d+)"', zipfile.ZipFile(io.BytesIO(r.hwpx_bytes)).read("Contents/section0.xml").decode())
        self.assertEqual(len(ids), len(set(ids)))

    def test_empty_box_skipped_and_reported(self):
        p = box_problem()
        p["content"]["stem"][1]["paragraphs"] = []
        r = run(p)
        self.assertEqual(r.report.stats["boxes"], 0)
        self.assertIn("BOX_EMPTY", r.report.codes())

    def test_old_paragraph_only_problem_unchanged(self):
        p = {"id": "p", "status": "confirmed", "content": {"stem": [{"type": "paragraph", "inlines": [t("가나다")]}]}}
        r = run(p)
        self.assertEqual(validate_package(r.hwpx_bytes), [])
        self.assertEqual(r.report.stats["boxes"], 0)


if __name__ == "__main__":
    unittest.main()
