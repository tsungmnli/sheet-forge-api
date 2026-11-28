"""쪽 번호 양식: dash("- 1 -" 쪽 번호 ctrl) / total("1 / 5" 꼬리말) / box(상자 안 "1 / 5" 꼬리말)."""
import io
import unittest
import zipfile

from app.export.hwpx import ExportMeta, ExportRequest, export_hwpx
from app.export.hwpx.errors import PresetError
from app.export.hwpx.preset import ExportPreset

META = ExportMeta(title="쪽 번호")


def problem():
    return {"id": "p1", "status": "confirmed", "content": {
        "stem": [{"type": "paragraph", "inlines": [{"t": "text", "v": "다음을 구하시오."}]}]}}


def section(style, enabled=True):
    preset = {"page_number": {"enabled": enabled, "style": style}}
    r = export_hwpx(ExportRequest([problem()], preset, META))
    return zipfile.ZipFile(io.BytesIO(r.hwpx_bytes)).read("Contents/section0.xml").decode("utf-8")


class PageNumberTest(unittest.TestCase):
    def test_default_style_is_dash(self):
        self.assertEqual(ExportPreset().page_number.style, "dash")

    def test_unknown_style_rejected(self):
        with self.assertRaises(PresetError):
            ExportPreset.from_dict({"page_number": {"enabled": True, "style": "roman"}}).validate()

    def test_dash_uses_page_num_ctrl(self):
        x = section("dash")
        self.assertEqual(x.count("<hp:pageNum "), 1)
        self.assertNotIn("<hp:footer", x)

    def test_total_footer_has_page_and_total(self):
        x = section("total")
        self.assertNotIn("<hp:pageNum ", x)
        self.assertEqual(x.count("<hp:footer "), 1)
        self.assertEqual(x.count('numType="PAGE"'), 1)
        self.assertEqual(x.count('numType="TOTAL_PAGE"'), 1)
        self.assertNotIn("<hp:tbl ", x)

    def test_box_footer_wraps_numbers_in_table(self):
        x = section("box")
        footer = x[x.index("<hp:footer "):x.index("</hp:footer>")]
        self.assertEqual(footer.count("<hp:tbl "), 2)   # 바깥 표 + 안쪽 대각선 표(sample.hwpx 구조)
        self.assertIn('numType="TOTAL_PAGE"', footer)

    def test_disabled_has_no_page_number(self):
        x = section("box", enabled=False)
        self.assertNotIn("<hp:pageNum ", x)
        self.assertNotIn("<hp:footer", x)


if __name__ == "__main__":
    unittest.main()
