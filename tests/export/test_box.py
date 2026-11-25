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


def plain_problem(title=""):
    """시험지.hwpx 24번처럼 제목 없는 조건 상자(수식 든 줄 + 일반 줄)."""
    return {"id": "p24", "status": "confirmed", "content": {
        "stem": [{"type": "paragraph", "inlines": [t("규칙에 따라 점수를 받을 수 있다.")]},
                 {"type": "box", "title": title, "paragraphs": [
                     line(t("주사위의 눈이 소수이고 주머니에서 검은 공이 나올 때 "), m("1"), t("점을 획득한다.")),
                     line(t("그 외의 경우는 점수를 획득하지 못한다."))]},
                 {"type": "paragraph", "inlines": [t("확률은?")]}],
        "choices": {"items": [[m(r"\frac{4}{25}")], [m(r"\frac{8}{25}")]]}}}


class PlainBox(unittest.TestCase):
    """제목 없는 상자 = 샘플 시험지.hwpx의 조건 상자: 묶음 개체 없이 hp:rect 하나."""

    def test_geometry_reproduces_sample_height(self):
        # 샘플: 글줄 3개(문단 1은 2줄) 글자 1000·줄 간격 160% → 글줄 4200 + 여유 2 x 1202 = 6604
        g = bg.plan_box(25795, "", [(2, False), (1, False)], 1000, 160)
        self.assertEqual((g.width, g.height, g.body_y, g.body_h), (25585, 6604, 0, 6604))
        self.assertEqual((g.title_w, g.title_h, g.title_x), (0, 0, 0))

    def test_blank_title_is_plain(self):
        self.assertEqual(bg.plan_box(25795, "   ", [(1, False)], 1000, 160), bg.plan_plain_box(25795, [(1, False)], 1000, 160))

    def test_export_single_rect_no_container_no_title(self):
        r = run(plain_problem())
        self.assertEqual(validate_package(r.hwpx_bytes), [])
        self.assertEqual(r.report.stats["boxes"], 1)
        sec = section(r)
        self.assertEqual(len(list(sec.iter(f"{{{HP}}}container"))), 0)
        rects = list(sec.iter(f"{{{HP}}}rect"))
        self.assertEqual(len(rects), 1)
        self.assertEqual((rects[0].get("groupLevel"), rects[0].get("numberingType")), ("0", "PICTURE"))
        xml = zipfile.ZipFile(io.BytesIO(r.hwpx_bytes)).read("Contents/section0.xml").decode()
        self.assertNotIn("< 보 기 >", xml)
        self.assertNotIn("보 기", xml)
        self.assertIn("그 외의 경우는 점수를 획득하지 못한다.", xml)

    def test_rect_size_matches_geometry_and_has_two_paragraphs_with_equation(self):
        sec = section(run(plain_problem()))
        rect = next(sec.iter(f"{{{HP}}}rect"))
        sz = rect.find(f"{{{HP}}}sz")
        self.assertEqual(int(sz.get("width")), 25585)       # 2단 한 단 폭 - 210
        self.assertGreater(int(sz.get("height")), 0)
        paras = list(rect.find(f"{{{HP}}}drawText").iter(f"{{{HP}}}p"))
        self.assertEqual(len(paras), 2)
        self.assertEqual(len(list(rect.iter(f"{{{HP}}}equation"))), 1)

    def test_with_title_still_container(self):
        r = run(plain_problem("<보기>"))
        self.assertEqual(validate_package(r.hwpx_bytes), [])
        self.assertEqual(len(list(section(r).iter(f"{{{HP}}}container"))), 1)

    def test_two_plain_boxes_unique_ids_and_deterministic(self):
        two = dict(plain_problem(), id="p25")
        a = export_hwpx(ExportRequest([plain_problem(), two], {"columns": {"count": 2, "gap_mm": None}}, META))
        b = export_hwpx(ExportRequest([plain_problem(), two], {"columns": {"count": 2, "gap_mm": None}}, META))
        self.assertEqual(validate_package(a.hwpx_bytes), [])
        self.assertEqual(a.hwpx_bytes, b.hwpx_bytes)
        ids = [e.get("id") for e in section(a).iter(f"{{{HP}}}rect")]
        self.assertEqual(len(ids), 2)
        self.assertEqual(len(set(ids)), 2)


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
