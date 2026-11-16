import io
import re
import unittest
import zipfile

from app.export.hwpx import ExportMeta, ExportRequest, ExportPreset, export_hwpx, plan_layout
from app.export.hwpx.preset import mm_to_hwp
from app.export.hwpx.validate import validate_package

META = ExportMeta("테스트", "2026-11-15T00:00:00Z")
T = lambda v: {"t": "text", "v": v}


def prob(pid, *inlines):
    return {"id": pid, "status": "confirmed",
            "content": {"stem": [{"type": "paragraph", "inlines": list(inlines)}],
                        "choices": {"items": [[T(str(k))] for k in range(1, 6)]}}}


def run(preset, n=2):
    ps = [prob(f"p{i}", T("값은 "), {"t": "math", "latex": "x^2+1"}, T("이다.")) for i in range(n)]
    return export_hwpx(ExportRequest(ps, preset, META))


def part(r, name):
    return zipfile.ZipFile(io.BytesIO(r.hwpx_bytes)).read(name).decode("utf-8")


class TestM5(unittest.TestCase):
    def test_numbering_format_and_start(self):
        r = run({"numbering": {"format": "{n}.", "start": 5}})
        s = part(r, "Contents/section0.xml")
        self.assertIn("<hp:t>5.</hp:t>", s)
        self.assertIn("<hp:t>6.</hp:t>", s)

    def test_align_options(self):
        self.assertEqual(plan_layout(ExportPreset.from_dict({"columns": {"count": 2}, "typography": {"align": "justify"}})).align, "JUSTIFY")
        self.assertEqual(plan_layout(ExportPreset.from_dict({"typography": {"align": "left"}})).align, "LEFT")
        self.assertEqual(plan_layout(ExportPreset.from_dict({"columns": {"count": 3}})).align, "LEFT")
        self.assertEqual(plan_layout(ExportPreset.from_dict({})).align, "JUSTIFY")

    def test_everything_at_once(self):
        preset = {"paper": {"kind": "B5", "width_mm": 182, "height_mm": 257}, "orientation": "landscape",
                  "margins_mm": {"top": 8, "header": 6, "bottom": 8, "footer": 6, "left": 12, "right": 14, "gutter": 10},
                  "columns": {"count": 3},
                  "typography": {"font_name": "맑은 고딕", "font_size_pt": 12, "line_spacing_pct": 130}}
        r = run(preset, 6)
        self.assertEqual(validate_package(r.hwpx_bytes), [])
        s, h = part(r, "Contents/section0.xml"), part(r, "Contents/header.xml")
        self.assertIn(f'<hp:pagePr landscape="NARROWLY" width="{mm_to_hwp(182)}" height="{mm_to_hwp(257)}" gutterType="LEFT_ONLY">', s)
        self.assertIn(f'gutter="{mm_to_hwp(10)}" left="{mm_to_hwp(12)}" right="{mm_to_hwp(14)}"', s)
        self.assertIn('colCount="3"', s)
        self.assertEqual(set(re.findall(r'baseUnit="(\d+)"', s)), {"1200"})
        self.assertIn('<hh:charPr id="0" height="1200"', h)
        self.assertIn('face="맑은 고딕"', h)
        self.assertIn('value="130"', h)
        # 본문 폭 = 쪽 가로(긴 변) − 왼쪽 − 오른쪽 − 제본
        self.assertEqual(r.layout["body_w"], mm_to_hwp(257) - mm_to_hwp(12) - mm_to_hwp(14) - mm_to_hwp(10))

    def test_deterministic_across_presets(self):
        p = {"columns": {"count": 2}, "orientation": "landscape"}
        self.assertEqual(run(p).hwpx_bytes, run(p).hwpx_bytes)
