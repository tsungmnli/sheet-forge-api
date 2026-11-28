"""머리 표식 [sample.hwpx 머리말]: 표식과 아래 선 사이에 간격이 있어야 한다(표 높이 4532, 칸 아래쪽 정렬, 줄간격 160%)."""
import io
import re
import unittest
import zipfile

from app.export.hwpx import ExportMeta, ExportRequest, export_hwpx
from app.export.hwpx.layout import plan_layout
from app.export.hwpx.preset import ExportPreset
from app.export.hwpx.section import (HEADER_MARK_H, HEADER_MARK_ROW_H, header_mark_need_h, header_mark_top)


def problem():
    return {"id": "p1", "status": "confirmed", "content": {
        "stem": [{"type": "paragraph", "inlines": [{"t": "text", "v": "다음을 구하시오."}]}]}}


def run(preset):
    r = export_hwpx(ExportRequest([problem()], preset, ExportMeta(title="중1 기말", subtitle="1학기")))
    z = zipfile.ZipFile(io.BytesIO(r.hwpx_bytes))
    return z.read("Contents/section0.xml").decode("utf-8"), z.read("Contents/header.xml").decode("utf-8")


def header_of(x):
    return x[x.index("<hp:header "):x.index("</hp:header>")]


class HeaderMarkSpacingTest(unittest.TestCase):
    def test_table_is_taller_than_mark_and_bottom_aligned(self):
        x, _ = run({"header_mark": {"text": "중1"}})
        hd = header_of(x)
        self.assertEqual(re.search(r'<hp:cellSz width="\d+" height="(\d+)"', hd).group(1), "4532")
        self.assertGreater(HEADER_MARK_ROW_H, HEADER_MARK_H + 2 * 141 + 600)   # 표식 + 줄간격 + 칸 여백보다 크다
        self.assertEqual(re.search(r'<hp:tc [^>]*>.*?vertAlign="(\w+)"', hd, re.S).group(1), "BOTTOM")
        self.assertIn('<hp:inMargin left="283" right="283" top="566" bottom="566"/>', hd)
        self.assertIn('vertOffset="301"', hd)

    def test_gap_between_mark_and_line_matches_sample(self):
        # 칸 아래 여백 141 + 줄간격 600 - 세로 오프셋 301 = 440 (1.5mm)
        gap = HEADER_MARK_ROW_H - header_mark_top() - HEADER_MARK_H
        self.assertEqual(gap, 440)

    def test_header_paragraphs_ignore_body_line_spacing(self):
        x, h = run({"header_mark": {"text": "중1"}, "typography": {"line_spacing_pct": 130}})
        for pid in set(re.findall(r'paraPrIDRef="(\d+)"', header_of(x))):
            m = re.search(r'<hh:paraPr id="%s" .*?</hh:paraPr>' % pid, h, re.S).group(0)
            self.assertEqual(set(re.findall(r'lineSpacing type="PERCENT" value="(\d+)"', m)), {"160"})

    def test_header_area_leaves_gap_below_line(self):
        # 머리말 영역 = 표 4532 + 선 아래 간격 1137 = 5669 (샘플). 프리셋 머리말 여백이 작으면 이만큼으로 올린다
        self.assertEqual(header_mark_need_h(), 5669)
        lay = plan_layout(ExportPreset.from_dict({"header_mark": {"text": "중1"}}))
        self.assertEqual(lay.header, 5669)
        x, _ = run({"header_mark": {"text": "중1"}})
        self.assertIn('<hp:margin header="5669"', x)

    def test_larger_header_margin_is_kept(self):
        lay = plan_layout(ExportPreset.from_dict({"header_mark": {"text": "중1"}, "margins_mm": {"header": 20}}))
        self.assertGreaterEqual(lay.header, 5669)
        self.assertIsNone(lay.header_raised_from)

    def test_no_mark_keeps_header_margin(self):
        lay = plan_layout(ExportPreset.from_dict({}))
        self.assertIsNone(lay.header_raised_from)

    def test_body_table_keeps_default_look(self):
        # table_xml 기본값은 그대로: 본문 표는 CENTER 정렬, 바깥 283
        from app.export.hwpx.builders import TablePart
        from app.export.hwpx.section import table_xml
        t = TablePart(rows=[[None]], col_w=[1000], row_h=[500], cell_pr=0, border_id=1)
        s = table_xml(1, 1, t, [["<hp:p/>"]])
        self.assertIn('vertAlign="CENTER"', s)
        self.assertIn('<hp:outMargin left="0" right="0" top="283" bottom="283"/>', s)
        self.assertIn('<hp:inMargin left="510" right="510" top="141" bottom="141"/>', s)


if __name__ == "__main__":
    unittest.main()
