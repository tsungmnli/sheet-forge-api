"""쪽 번호 상자(box) [sample.hwpx 꼬리말]: 바깥 1×1 표 → 가운데 문단 → 안쪽 1×1 표(대각선) → 문단 둘(쪽 번호·전체 쪽수)."""
import io
import re
import unittest
import zipfile

from app.export.hwpx import ExportMeta, ExportRequest, export_hwpx
from app.export.hwpx.layout import plan_layout
from app.export.hwpx.preset import ExportPreset
from app.export.hwpx.section import (FOOTER_INNER_H, FOOTER_INNER_W, FOOTER_OUTER_H, footer_box_bottom,
                                     footer_need_h)


def problem():
    return {"id": "p1", "status": "confirmed", "content": {
        "stem": [{"type": "paragraph", "inlines": [{"t": "text", "v": "다음을 구하시오."}]}]}}


def run(style="box", extra=None):
    preset = {"page_number": {"enabled": True, "style": style}}
    preset.update(extra or {})
    r = export_hwpx(ExportRequest([problem()], preset, ExportMeta(title="쪽 번호")))
    z = zipfile.ZipFile(io.BytesIO(r.hwpx_bytes))
    return z.read("Contents/section0.xml").decode("utf-8"), z.read("Contents/header.xml").decode("utf-8")


def footer_of(x):
    return x[x.index("<hp:footer "):x.index("</hp:footer>")]


def para_pr(header, pid):
    return re.search(rf'<hh:paraPr id="{pid}" .*?</hh:paraPr>', header, re.S).group(0)


class PageNumberBoxTest(unittest.TestCase):
    def test_two_nested_tables_with_sample_sizes(self):
        x, _ = run()
        f = footer_of(x)
        sizes = re.findall(r'<hp:sz width="(\d+)" widthRelTo="ABSOLUTE" height="(\d+)"', f)
        self.assertEqual(len(sizes), 2)
        self.assertEqual(sizes[0][1], str(FOOTER_OUTER_H))   # 3826
        self.assertEqual(sizes[1], (str(FOOTER_INNER_W), str(FOOTER_INNER_H)))   # 5032 x 2132
        self.assertEqual(FOOTER_OUTER_H, 3826)

    def test_outer_table_spans_body_width_minus_out_margin(self):
        x, _ = run()
        f = footer_of(x)
        text_w = int(re.search(r'textWidth="(\d+)"', f).group(1))
        outer_w = int(re.search(r'<hp:sz width="(\d+)"', f).group(1))
        self.assertEqual(outer_w, text_w - 2 * 283)

    def test_numbers_are_two_paragraphs_in_inner_cell_without_slash_text(self):
        x, _ = run()
        f = footer_of(x)
        inner = f[f.rindex("<hp:tbl "):]
        self.assertEqual(inner.count('numType="PAGE"'), 1)
        self.assertEqual(inner.count('numType="TOTAL_PAGE"'), 1)
        sub = inner[inner.index("<hp:subList"):inner.index("</hp:subList>")]
        self.assertEqual(sub.count("<hp:p "), 2)
        self.assertNotIn("<hp:t> / </hp:t>", f)   # 문자 "/"는 없고 대각선은 칸 테두리가 그린다

    def test_diagonal_comes_from_cell_border_fill(self):
        x, h = run()
        f = footer_of(x)
        inner = f[f.rindex("<hp:tbl "):]
        bid = re.search(r'<hp:tc [^>]*borderFillIDRef="(\d+)"', inner).group(1)
        bf = re.search(rf'<hh:borderFill id="{bid}" .*?</hh:borderFill>', h, re.S).group(0)
        self.assertIn('<hh:slash type="CENTER"', bf)
        self.assertEqual(bf.count('type="SOLID"'), 5)   # 네 면 + 대각선

    def test_outer_table_has_no_border(self):
        x, h = run()
        f = footer_of(x)
        bid = re.search(r'<hp:tc [^>]*borderFillIDRef="(\d+)"', f).group(1)   # 첫 칸 = 바깥 표 칸
        bf = re.search(rf'<hh:borderFill id="{bid}" .*?</hh:borderFill>', h, re.S).group(0)
        self.assertNotIn('Border type="SOLID"', bf)
        self.assertIn('<hh:slash type="NONE"', bf)

    def test_number_paragraphs_overlap_with_40_percent_spacing(self):
        x, h = run()
        f = footer_of(x)
        inner = f[f.rindex("<hp:tbl "):]
        ids = re.findall(r'<hp:p id="\d+" paraPrIDRef="(\d+)"', inner)
        self.assertEqual(len(ids), 2)
        left, right = para_pr(h, ids[0]), para_pr(h, ids[1])
        self.assertIn('horizontal="LEFT"', left)
        self.assertIn('horizontal="RIGHT"', right)
        for p in (left, right):
            self.assertEqual(len(re.findall(r'<hh:lineSpacing type="PERCENT" value="40"', p)), 2)

    def test_footer_paragraph_spacing_ignores_body_line_spacing(self):
        x, h = run(extra={"typography": {"line_spacing_pct": 130}})
        f = footer_of(x)
        first = re.search(r'<hp:p id="\d+" paraPrIDRef="(\d+)"', f).group(1)   # 바깥 표를 담는 문단
        self.assertIn('<hh:lineSpacing type="PERCENT" value="150"', para_pr(h, first))

    def test_footer_char_is_12pt(self):
        x, h = run()
        f = footer_of(x)
        inner = f[f.rindex("<hp:tbl "):]
        cid = re.search(r'<hp:run charPrIDRef="(\d+)"><hp:ctrl><hp:autoNum', inner).group(1)
        self.assertIn('height="1200"', re.search(rf'<hh:charPr id="{cid}" [^>]*>', h).group(0))

    def test_need_height_covers_outer_table(self):
        self.assertEqual(footer_need_h(True, "box", 1000, 160), FOOTER_OUTER_H + 2 * 283)
        p = ExportPreset.from_dict({"page_number": {"enabled": True, "style": "box"}})
        lay = plan_layout(p)
        self.assertGreaterEqual(lay.footer, footer_need_h(True, "box", 1000, 160))
        x, _ = run()
        self.assertIn(f'footer="{lay.footer}"', x)

    def test_preview_box_matches_inner_table(self):
        from app.export.hwpx.preview import page_preview
        p = ExportPreset.from_dict({"page_number": {"enabled": True, "style": "box"}})
        box = page_preview(p, plan_layout(p), "t", "")["page_number_box"]
        self.assertEqual((box["w_mm"], box["h_mm"]), (17.75, 7.52))
        self.assertGreater(box["bottom_mm"], 0)
        self.assertGreater(footer_box_bottom(), 0)

    def test_dash_and_total_unchanged(self):
        x, _ = run("total")
        self.assertNotIn("<hp:tbl ", x)
        self.assertEqual(x.count('<hp:t> / </hp:t>'), 1)
        x, _ = run("dash")
        self.assertEqual(x.count("<hp:pageNum "), 1)


if __name__ == "__main__":
    unittest.main()
