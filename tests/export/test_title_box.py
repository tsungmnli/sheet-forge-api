"""첫 쪽 제목 상자: 켜져 있고 제목이 있을 때만 맨 앞에 상자 하나를 넣는다(빈 줄 없음)."""
import io
import re
import unittest
import zipfile

from app.export.hwpx import ExportMeta, ExportRequest, export_hwpx
from app.export.hwpx.errors import PresetError
from app.export.hwpx.preset import ExportPreset


def problem():
    return {"id": "p1", "status": "confirmed", "content": {
        "stem": [{"type": "paragraph", "inlines": [{"t": "text", "v": "다음을 구하시오."}]}]}}


def run(preset, title="중1 기말", subtitle="1학기"):
    r = export_hwpx(ExportRequest([problem()], preset, ExportMeta(title=title, subtitle=subtitle)))
    x = zipfile.ZipFile(io.BytesIO(r.hwpx_bytes)).read("Contents/section0.xml").decode("utf-8")
    return r, x


class TitleBoxTest(unittest.TestCase):
    def test_default_is_off(self):
        self.assertFalse(ExportPreset().title_box.enabled)
        _, x = run({})
        self.assertNotIn("중1 기말", x)

    def test_on_puts_title_and_subtitle_before_problem(self):
        _, x = run({"title_box": {"enabled": True}})
        self.assertIn("중1 기말", x)
        self.assertIn("1학기", x)
        self.assertLess(x.index("중1 기말"), x.index("다음을 구하시오."))

    def test_two_columns_split_after_title_table(self):
        # [sample.hwpx] 제목 표는 1단 구역, 다음 문단 맨 앞에서 2단으로 나눈다
        _, x = run({"title_box": {"enabled": True}, "columns": {"count": 2}})
        cols = [m for m in re.findall(r'colCount="(\d)"', x)]
        self.assertEqual(cols, ["1", "2"])
        self.assertLess(x.index("<hp:tbl "), x.rindex('colCount="2"'))
        self.assertLess(x.rindex('colCount="2"'), x.index("다음을 구하시오."))

    def test_one_column_has_single_col_setting(self):
        _, x = run({"title_box": {"enabled": True}})
        self.assertEqual(re.findall(r'colCount="(\d)"', x), ["1"])

    def test_sizes_follow_sample(self):
        # [sample.hwpx] 첫 줄 20pt, 둘째 줄 32pt, 칸 테두리는 아래 0.5mm 선만
        r, x = run({"title_box": {"enabled": True}})
        h = zipfile.ZipFile(io.BytesIO(r.hwpx_bytes)).read("Contents/header.xml").decode("utf-8")
        sizes = {int(i): int(z) for i, z in re.findall(r'<hh:charPr id="(\d+)" height="(\d+)"', h)}
        used = [int(i) for i in re.findall(r'charPrIDRef="(\d+)"><hp:t>(?:중1 기말|1학기)', x)]
        self.assertEqual([sizes[i] for i in used], [2000, 3200])
        self.assertIn('width="0.5 mm"', h)

    def test_only_title_is_big(self):
        r, x = run({"title_box": {"enabled": True}}, subtitle="")
        h = zipfile.ZipFile(io.BytesIO(r.hwpx_bytes)).read("Contents/header.xml").decode("utf-8")
        sizes = {int(i): int(z) for i, z in re.findall(r'<hh:charPr id="(\d+)" height="(\d+)"', h)}
        i = int(re.search(r'charPrIDRef="(\d+)"><hp:t>중1 기말', x).group(1))
        self.assertEqual(sizes[i], 3200)

    def test_no_blank_line_and_height_matches_sample(self):
        # [sample.hwpx] 제목 표 안은 문단 2개뿐이고 표 높이는 9032(= 3200 + 5120 + 282 + 430)
        _, x = run({"title_box": {"enabled": True}})
        tbl = x[x.index("<hp:tbl "):x.index("</hp:tbl>")]
        self.assertEqual(tbl.count("<hp:p "), 2)
        self.assertIn('<hp:sz width="%s" widthRelTo="ABSOLUTE" height="9032"' % re.search(r'<hp:sz width="(\d+)"', tbl).group(1), tbl)
        self.assertIn('<hp:cellSz', tbl)
        self.assertEqual(re.search(r'<hp:cellSz width="\d+" height="(\d+)"', tbl).group(1), "9032")

    def test_only_title_height(self):
        _, x = run({"title_box": {"enabled": True}}, subtitle="")
        tbl = x[x.index("<hp:tbl "):x.index("</hp:tbl>")]
        self.assertEqual(tbl.count("<hp:p "), 1)
        self.assertEqual(re.search(r'<hp:cellSz width="\d+" height="(\d+)"', tbl).group(1), str(5120 + 282 + 430))

    def test_empty_title_skips_with_warning(self):
        r, x = run({"title_box": {"enabled": True}}, title="")
        self.assertIn("TITLE_BOX_NO_TITLE", [i["code"] for i in r.report.to_dict()["items"]])

    def test_non_bool_rejected(self):
        with self.assertRaises(PresetError):
            ExportPreset.from_dict({"title_box": {"enabled": "yes"}}).validate()


if __name__ == "__main__":
    unittest.main()
