import io
import re
import unittest
import zipfile

from app.export.hwpx import (EmptyExportError, ExportMeta, ExportPreset, ExportRequest, PresetError,
                             UnconfirmedProblemError, export_hwpx, plan_layout)
from app.export.hwpx.builders import build_problem_paragraphs
from app.export.hwpx.preset import mm_to_hwp
from app.export.hwpx.report import ExportReport
from app.export.hwpx.validate import validate_package

META = ExportMeta("테스트", "2026-11-15T00:00:00Z")


def prob(i, text="다음 중 옳은 것은?", status="confirmed", paras=1):
    return {"id": f"p{i}", "status": status,
            "content": {"stem": [{"type": "paragraph", "inlines": [{"t": "text", "v": f"{text} {k}"}]}
                                 for k in range(paras)]}}


def run(problems, preset=None):
    return export_hwpx(ExportRequest(problems, preset, META))


def parts(data):
    z = zipfile.ZipFile(io.BytesIO(data))
    return {n: z.read(n) for n in z.namelist()}, z


class Units(unittest.TestCase):
    def test_mm_to_hwp(self):
        self.assertEqual(mm_to_hwp(5), 1417)
        self.assertEqual(mm_to_hwp(10), 2835)


class LayoutGolden(unittest.TestCase):  # 설계 5.3 골든 수치
    def body(self, d):
        return plan_layout(ExportPreset.from_dict(d))

    def test_default(self):
        self.assertEqual(self.body({}).body_w, 53858)

    def test_a4_portrait_12_14(self):
        self.assertEqual(self.body({"margins_mm": {"left": 12, "right": 14}}).body_w, 52157)

    def test_gutter(self):
        self.assertEqual(self.body({"margins_mm": {"left": 12, "right": 14, "gutter": 10}}).body_w, 49322)

    def test_landscape(self):
        lc = self.body({"orientation": "landscape", "margins_mm": {"left": 12, "right": 14}})
        self.assertEqual(lc.body_w, 76815)
        self.assertEqual((lc.page_w, lc.page_h, lc.landscape_attr), (59528, 84186, "NARROWLY"))

    def test_b5_three_columns(self):
        lc = self.body({"paper": {"kind": "B5", "width_mm": 182, "height_mm": 257},
                        "margins_mm": {"left": 12, "right": 14},
                        "columns": {"count": 3, "gap_mm": 4}})
        self.assertEqual(lc.col_w, 13984)

    def test_default_gaps_and_align(self):
        self.assertEqual(self.body({"columns": {"count": 2}}).col_gap, 2268)
        self.assertEqual(self.body({"columns": {"count": 3}}).col_gap, 1134)
        self.assertEqual(self.body({}).align, "JUSTIFY")
        self.assertEqual(self.body({"columns": {"count": 2}}).align, "LEFT")
        self.assertEqual(self.body({"columns": {"count": 2}, "typography": {"align": "justify"}}).align, "JUSTIFY")


class PresetValidation(unittest.TestCase):
    def bad(self, d, code):
        with self.assertRaises(PresetError) as cm:
            plan_layout(ExportPreset.from_dict(d))
        self.assertIn(code, [c for c, _ in cm.exception.errors])

    def test_cases(self):
        self.bad({"columns": {"count": 4}}, "PRESET_COLUMNS")
        self.bad({"typography": {"font_size_pt": 30}}, "PRESET_FONT_SIZE")
        self.bad({"typography": {"line_spacing_pct": 50}}, "PRESET_LINE_SPACING")
        self.bad({"margins_mm": {"left": -1}}, "PRESET_MARGINS")
        self.bad({"margins_mm": {"left": 110, "right": 110}}, "PRESET_MARGINS")
        self.bad({"margins_mm": {"left": 100, "right": 100}}, "PRESET_COLUMN_WIDTH")
        self.bad({"margins_mm": {"top": 80, "bottom": 80}}, "PRESET_MARGINS")
        self.bad({"columns": {"count": 3}, "margins_mm": {"left": 60, "right": 60}}, "PRESET_COLUMN_WIDTH")
        self.bad({"orientation": "diagonal"}, "PRESET_ORIENTATION")
        self.bad({"nope": 1}, "PRESET_UNKNOWN_KEY")
        self.bad({"numbering": {"format": "{x}"}}, "PRESET_NUMBERING")


class KeepRules(unittest.TestCase):  # 설계 7·8장
    def test_keep_by_position(self):
        specs = build_problem_paragraphs(prob(1, paras=2), "01", ExportReport())
        self.assertEqual([(s.role, s.keep_with_next, s.keep_lines) for s in specs],
                         [("number", True, True), ("body", True, True), ("body", False, True)])

    def test_number_only_problem(self):
        p = {"id": "x", "status": "confirmed", "content": {"stem": []}}
        specs = build_problem_paragraphs(p, "01", ExportReport())
        self.assertEqual([(s.keep_with_next, s.keep_lines) for s in specs], [(False, True)])


class Export(unittest.TestCase):
    def test_structure_and_validation(self):
        r = run([prob(1), prob(2)])
        self.assertEqual(validate_package(r.hwpx_bytes), [])
        p, z = parts(r.hwpx_bytes)
        names = z.namelist()
        self.assertEqual(names[0], "mimetype")
        self.assertEqual(z.getinfo("mimetype").compress_type, zipfile.ZIP_STORED)
        self.assertEqual(z.getinfo("version.xml").compress_type, zipfile.ZIP_STORED)
        self.assertFalse(any(n.startswith("Preview/") for n in names))
        self.assertNotIn(b"Preview/", p["META-INF/container.xml"])

    def test_no_personal_info(self):
        p, _ = parts(run([prob(1)]).hwpx_bytes)
        self.assertNotIn(b"wenna", p["Contents/content.hpf"])
        self.assertIn("2026-11-15T00:00:00Z".encode(), p["Contents/content.hpf"])
        self.assertIn("테스트".encode(), p["Contents/content.hpf"])

    def test_deterministic(self):
        a = run([prob(1), prob(2)]).hwpx_bytes
        b = run([prob(1), prob(2)]).hwpx_bytes
        self.assertEqual(a, b)

    def test_numbering_and_text(self):
        p, _ = parts(run([prob(1), prob(2)], {"numbering": {"format": "{n:03d}", "start": 7}}).hwpx_bytes)
        sec = p["Contents/section0.xml"].decode()
        self.assertIn("<hp:t>007</hp:t>", sec)
        self.assertIn("<hp:t>008</hp:t>", sec)

    def test_xml_escape(self):
        p, _ = parts(run([prob(1, text="a<b & c>d")]).hwpx_bytes)
        self.assertIn("a&lt;b &amp; c&gt;d", p["Contents/section0.xml"].decode())

    def test_page_and_columns_patched(self):
        r = run([prob(1)], {"orientation": "landscape", "columns": {"count": 3},
                            "margins_mm": {"left": 12, "right": 14, "gutter": 10}})
        sec = parts(r.hwpx_bytes)[0]["Contents/section0.xml"].decode()
        self.assertIn('landscape="NARROWLY" width="59528" height="84186"', sec)
        self.assertIn('colCount="3" sameSz="1" sameGap="1134"', sec)
        self.assertIn('left="3402" right="3969"', sec)
        self.assertIn('gutter="2835"', sec)
        self.assertEqual(sec.count("<hp:secPr"), 1)
        self.assertEqual(sec.count("<hp:colPr"), 1)

    def test_namespaces_preserved(self):
        sec = parts(run([prob(1)]).hwpx_bytes)[0]["Contents/section0.xml"].decode()
        self.assertTrue(sec.startswith('<?xml version="1.0" encoding="UTF-8" standalone="yes" ?><hs:sec xmlns:ha='))

    def test_registry_dedup_and_ids(self):
        r = run([prob(1, paras=2), prob(2, paras=2)])
        hdr = parts(r.hwpx_bytes)[0]["Contents/header.xml"].decode()
        # 기본 0~19 + 새 항목: (non-last keep) (last) (blank) = 3
        self.assertIn('<hh:paraProperties itemCnt="23">', hdr)
        self.assertEqual(r.report.stats["new_para_pr"], 3)
        ids = [int(x) for x in re.findall(r'<hh:paraPr id="(\d+)"', hdr)]
        self.assertEqual(ids, list(range(23)))

    def test_paraPr_contents(self):
        hdr = parts(run([prob(1)], {"typography": {"line_spacing_pct": 130}, "columns": {"count": 2}})
                    .hwpx_bytes)[0]["Contents/header.xml"].decode()
        new = hdr[hdr.index('<hh:paraPr id="20"'):hdr.index("</hh:paraProperties>")]
        self.assertEqual(new.count('lineSpacing type="PERCENT" value="130"'), 2 * 3)  # 3개 × 두 곳
        self.assertIn('horizontal="LEFT"', new)
        self.assertNotIn("JUSTIFY", new)
        self.assertIn('keepWithNext="1" keepLines="1"', new)
        self.assertIn('keepWithNext="0" keepLines="1"', new)
        self.assertIn('keepWithNext="0" keepLines="0"', new)  # 빈 문단

    def test_font_and_size(self):
        hdr = parts(run([prob(1)], {"typography": {"font_name": "맑은 고딕", "font_size_pt": 12}})
                    .hwpx_bytes)[0]["Contents/header.xml"].decode()
        self.assertIn('<hh:fontface lang="HANGUL" fontCnt="3">', hdr)
        self.assertIn('<hh:fontface lang="LATIN" fontCnt="3">', hdr)
        self.assertIn('<hh:font id="2" face="맑은 고딕"', hdr)
        c0 = hdr[hdr.index('<hh:charPr id="0"'):]
        self.assertTrue(c0.startswith('<hh:charPr id="0" height="1200"'))
        self.assertIn('<hh:fontRef hangul="2" latin="2"', c0[:900])

    def test_existing_font_reused(self):
        hdr = parts(run([prob(1)]).hwpx_bytes)[0]["Contents/header.xml"].decode()
        self.assertIn('<hh:fontface lang="HANGUL" fontCnt="2">', hdr)

    def test_template_items_untouched(self):
        orig = zipfile.ZipFile("assets/templates/blank.hwpx").read("Contents/header.xml").decode()
        new = parts(run([prob(1)]).hwpx_bytes)[0]["Contents/header.xml"].decode()
        for i in range(20):
            m = re.search(rf'<hh:paraPr id="{i}" .*?</hh:paraPr>', orig, re.S).group(0)
            self.assertIn(m, new)

    def test_unconfirmed(self):
        r = run([prob(1), prob(2, status="needs_review")])
        self.assertIn("NOT_CONFIRMED", r.report.codes())
        self.assertEqual(r.report.stats["problems"], 1)
        with self.assertRaises(UnconfirmedProblemError):
            run([prob(1, status="needs_review")], {"on_unconfirmed": "fail"})

    def test_empty(self):
        with self.assertRaises(EmptyExportError):
            run([])
        with self.assertRaises(EmptyExportError):
            run([prob(1, status="recognizing")])

    def test_not_implemented_reported(self):
        p = prob(1)
        p["content"]["stem"][0]["inlines"].append({"t": "math", "latex": r"a\approx b"})  # 렌더링 미확인 어휘 → 폴백
        p["content"]["choices"] = {"items": [[{"t": "text", "v": "1"}]]}
        p["content"]["stem"][0]["inlines"].append({"t": "image", "ref": "x"})  # 인라인 그림은 후속
        r = run([p])
        self.assertEqual(r.report.codes().count("NOT_IMPLEMENTED"), 1)  # 인라인 그림만(선택지는 M3, 그림 블록은 M4)
        self.assertIn("UNSUPPORTED_MATH", r.report.codes())
        self.assertIn(r"[수식 오류: a\approx b]", parts(r.hwpx_bytes)[0]["Contents/section0.xml"].decode())

    def test_many_problems_validate(self):
        r = run([prob(i, paras=3) for i in range(1, 60)], {"columns": {"count": 3}})
        self.assertEqual(validate_package(r.hwpx_bytes), [])


if __name__ == "__main__":
    unittest.main()
