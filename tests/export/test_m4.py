import io
import re
import struct
import unittest
import zipfile
import zlib

from app.export.hwpx import EmptyExportError, ExportMeta, ExportRequest, export_hwpx
from app.export.hwpx.builders import Picture, build_problem_paragraphs
from app.export.hwpx.images import ImageData
from app.export.hwpx.report import ExportReport
from app.export.hwpx.validate import validate_package

META = ExportMeta("테스트", "2026-11-15T00:00:00Z")


def make_png(w, h):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    rows = b"".join(b"\x00" + bytes((200, 200, 220)) * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


IMAGES = {"a": ImageData(make_png(40, 30), 400, 300), "b": ImageData(make_png(20, 20), 200, 200)}
provider = IMAGES.get


def fig(ref="a", **kw):
    return {"id": "f_" + ref, "clean_ref": ref, "use": "clean", "placement": "after_stem", **kw}


def prob(figures, pid="p1", choices=None):
    c = {"stem": [{"type": "paragraph", "inlines": [{"t": "text", "v": "그림을 보고 답하시오."}]}], "figures": figures}
    if choices:
        c["choices"] = {"items": [[{"t": "text", "v": x}] for x in choices]}
    return {"id": pid, "status": "confirmed", "content": c}


def run(problems, preset=None, images=provider):
    return export_hwpx(ExportRequest(problems, preset, META, images))


def parts(r):
    z = zipfile.ZipFile(io.BytesIO(r.hwpx_bytes))
    return {n: z.read(n) for n in z.namelist()}


def sec(r):
    return parts(r)["Contents/section0.xml"].decode()


def pic_sizes(xml):
    return re.findall(r'<hp:sz width="(\d+)" widthRelTo="ABSOLUTE" height="(\d+)"', xml.split("<hp:pic ", 1)[1])


class TestFigures(unittest.TestCase):
    def test_default_size_from_pixels(self):  # 400×300px × 75
        r = run([prob([fig()])])
        self.assertEqual(pic_sizes(sec(r))[0], ("30000", "22500"))
        self.assertNotIn("FIGURE_SHRUNK", r.report.codes())
        self.assertEqual(validate_package(r.hwpx_bytes), [])

    def test_width_mm(self):
        r = run([prob([fig(width_mm=45)])])  # 45mm = 12756
        self.assertEqual(pic_sizes(sec(r))[0], ("12756", "9567"))

    def test_preset_default_width(self):
        r = run([prob([fig()])], {"figures": {"default_width_mm": 45}})
        self.assertEqual(pic_sizes(sec(r))[0][0], "12756")

    def test_shrunk_to_column(self):
        r = run([prob([fig()])], {"columns": {"count": 3}, "margins_mm": {"left": 30, "right": 30}})
        col_w = r.layout["col_w"]
        w, h = pic_sizes(sec(r))[0]
        self.assertEqual(int(w), col_w)
        self.assertEqual(int(h), round(col_w * 300 / 400))
        self.assertIn("FIGURE_SHRUNK", r.report.codes())

    def test_tall_warning(self):
        r = run([prob([fig(width_mm=190)])], {"paper": {"kind": "A4", "width_mm": 210, "height_mm": 297}})
        self.assertNotIn("FIGURE_TALL", r.report.codes())  # 190×142mm는 쪽 안
        r = run([prob([fig("b", width_mm=190)])])  # 190×190mm
        self.assertNotIn("FIGURE_TALL", r.report.codes())
        r = run([prob([fig("b", width_mm=190)])], {"margins_mm": {"top": 100, "bottom": 5, "header": 10, "footer": 10}})
        self.assertIn("FIGURE_TALL", r.report.codes())

    def test_bindata_and_manifest(self):
        r = run([prob([fig("a"), fig("b")], "p1"), prob([fig("a")], "p2")])
        p = parts(r)
        self.assertEqual([n for n in p if n.startswith("BinData/")],
                         ["BinData/image1.png", "BinData/image2.png", "BinData/image3.png"])
        self.assertEqual(p["BinData/image2.png"], IMAGES["b"].png)
        hpf = p["Contents/content.hpf"].decode()
        for k in (1, 2, 3):
            self.assertIn(f'<opf:item id="image{k}" href="BinData/image{k}.png" media-type="image/png" isEmbeded="1"/>', hpf)
        self.assertEqual(r.report.stats["figures"], 3)
        self.assertEqual(validate_package(r.hwpx_bytes), [])

    def test_unique_ids(self):
        r = run([prob([fig("a"), fig("b")], "p1"), prob([fig("a")], "p2")])
        ids = re.findall(r'<hp:pic id="(\d+)" zOrder="(\d+)"', sec(r))
        self.assertEqual(len(set(i for i, _ in ids)), 3)
        self.assertEqual(len(set(z for _, z in ids)), 3)

    def test_missing_excludes_problem_and_keeps_numbering(self):
        r = run([prob([fig("zzz")], "bad"), prob([fig("a")], "ok")])
        self.assertIn("FIGURE_MISSING", r.report.codes())
        self.assertEqual(r.report.stats["problems"], 1)
        s = sec(r)
        self.assertIn("01", s)
        self.assertNotIn("02", s)  # 제외된 문항은 번호를 쓰지 않음

    def test_no_provider_and_all_missing(self):
        with self.assertRaises(EmptyExportError):
            run([prob([fig()])], images=None)

    def test_provider_object_and_error(self):
        class P:
            def get(self, ref):
                raise OSError("boom")
        with self.assertRaises(EmptyExportError):
            run([prob([fig()])], images=P())

    def test_not_png(self):
        bad = {"a": ImageData(b"GIF89a", 10, 10)}
        with self.assertRaises(EmptyExportError):
            run([prob([fig()])], images=bad.get)

    def test_placement_order_and_keep(self):
        r = ExportReport()
        a = build_problem_paragraphs(prob([fig()], choices=["1", "2"]), "01", r, None, 0.1, provider)
        self.assertEqual([s.role for s in a], ["number", "body", "figure", "choice"])
        b = build_problem_paragraphs(prob([fig(placement="after_choices")], choices=["1", "2"]), "01", r, None, 0.1, provider)
        self.assertEqual([s.role for s in b], ["number", "body", "choice", "figure"])
        self.assertTrue(all(s.keep_with_next for s in b[:-1]))
        self.assertFalse(b[-1].keep_with_next)
        self.assertTrue(b[-1].keep_lines)
        self.assertIsInstance(b[-1].parts[0], Picture)

    def test_deterministic(self):
        ps = [prob([fig("a")], "p1", ["1", "2", "3"])]
        self.assertEqual(run(ps).hwpx_bytes, run(ps).hwpx_bytes)

    def test_raw_use(self):
        f = {"id": "f", "raw_ref": "b", "clean_ref": "a", "use": "raw"}
        r = run([prob([f])])
        self.assertEqual(parts(r)["BinData/image1.png"], IMAGES["b"].png)
