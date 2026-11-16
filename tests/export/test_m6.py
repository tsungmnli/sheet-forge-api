"""M6: 리포트 코드별 시나리오, 사후 검증의 실패 검출, 임의 입력 속성 테스트(설계 14장 1·3)."""
import io
import json
import random
import re
import struct
import unittest
import zipfile
import zlib

from app.export.hwpx import (EmptyExportError, ExportMeta, ExportRequest, InternalValidationError,
                             PresetError, UnconfirmedProblemError, export_hwpx)
from app.export.hwpx.images import ImageData
from app.export.hwpx.validate import assert_valid, validate_package

META = ExportMeta("테스트", "2026-11-15T00:00:00Z")
T = lambda v, **kw: {"t": "text", "v": v, **kw}
M = lambda latex: {"t": "math", "latex": latex}


def make_png(w, h):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    rows = b"".join(b"\x00" + bytes((200, 200, 220)) * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


IMAGES = {"a": ImageData(make_png(40, 30), 400, 300), "b": ImageData(make_png(20, 20), 200, 200)}


def prob(*inlines, pid="p1", status="confirmed", items=None, figures=None):
    c = {"stem": [{"type": "paragraph", "inlines": list(inlines)}]}
    if items is not None:
        c["choices"] = {"items": items}
    if figures is not None:
        c["figures"] = figures
    return {"id": pid, "status": status, "content": c}


def run(problems, preset=None, images=IMAGES.get):
    return export_hwpx(ExportRequest(problems, preset, META, images))


def items_of(r, code):
    return [i for i in r.report.items if i.code == code]


class ReportScenarios(unittest.TestCase):
    """리포트 코드 중 앞 마일스톤 테스트에 없던 것과, 리포트 구조 자체."""

    def test_text_format_ignored(self):
        r = run([prob(T("굵게", bold=True), pid="px")])
        it = items_of(r, "TEXT_FORMAT_IGNORED")[0]
        self.assertEqual((it.severity, it.problem_id, it.where), ("info", "px", "stem[0].inline[0]"))

    def test_font_not_verified_always_and_status_ok(self):
        r = run([prob(T("가"))])
        self.assertEqual(r.report.codes(), ["FONT_NOT_VERIFIED"])
        self.assertEqual(r.report.status, "ok")  # info만 있으면 ok

    def test_warn_makes_status_warnings(self):
        r = run([prob(T("가"), pid="a"), prob(T("나"), pid="b", status="needs_review")])
        self.assertIn("NOT_CONFIRMED", r.report.codes())
        self.assertEqual(r.report.status, "warnings")
        self.assertEqual(items_of(r, "NOT_CONFIRMED")[0].problem_id, "b")

    def test_error_severity_for_missing_figure(self):
        r = run([prob(T("가"), pid="a"), prob(T("나"), pid="b", figures=[{"id": "f", "clean_ref": "nope"}])])
        it = items_of(r, "FIGURE_MISSING")[0]
        self.assertEqual((it.severity, it.problem_id), ("error", "b"))
        self.assertEqual(r.report.status, "warnings")

    def test_report_is_json_serializable_and_complete(self):
        r = run([prob(T("값은 "), M("x^2"), items=[[T("1")], [T("2")]], figures=[{"id": "f", "clean_ref": "a"}])])
        d = json.loads(json.dumps(r.report.to_dict(), ensure_ascii=False))
        self.assertEqual(set(d), {"status", "items", "stats", "layout", "effective_preset"})
        for k in ("problems", "equations", "figures", "choice_rows"):
            self.assertIn(k, d["stats"])
        self.assertEqual((d["stats"]["problems"], d["stats"]["equations"], d["stats"]["figures"]), (1, 1, 1))
        self.assertEqual(d["layout"]["col_w"], r.layout["col_w"])
        self.assertEqual(d["effective_preset"]["columns"]["count"], 1)

    def test_errors_instead_of_reports(self):
        with self.assertRaises(EmptyExportError):
            run([])
        with self.assertRaises(PresetError):
            run([prob(T("가"))], {"columns": {"count": 9}})
        with self.assertRaises(UnconfirmedProblemError):
            run([prob(T("가"), status="needs_review")], {"on_unconfirmed": "fail"})


def mutate(data: bytes, fn) -> bytes:
    """zip을 열어 fn(parts: dict)로 고친 뒤 mimetype을 첫 항목으로 다시 묶는다."""
    z = zipfile.ZipFile(io.BytesIO(data))
    parts = {n: z.read(n) for n in z.namelist()}
    fn(parts)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as o:
        for n in ["mimetype"] + [k for k in parts if k != "mimetype"]:
            o.writestr(zipfile.ZipInfo(n, (1980, 1, 1, 0, 0, 0)), parts[n],
                       zipfile.ZIP_STORED if n == "mimetype" else zipfile.ZIP_DEFLATED)
    return buf.getvalue()


def sub_part(name, pattern, repl):
    def fn(parts):
        new, n = re.subn(pattern, repl, parts[name].decode("utf-8"), count=1)
        assert n == 1, pattern
        parts[name] = new.encode("utf-8")
    return fn


class ValidateDetects(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.good = run([prob(T("값은 "), M("x^2"), items=[[T("1")], [T("2")], [T("3")]],
                             figures=[{"id": "f", "clean_ref": "a"}])]).hwpx_bytes

    def bad(self, fn, needle):
        data = mutate(self.good, fn)
        problems = validate_package(data)
        self.assertTrue(any(needle in p for p in problems), (needle, problems))
        with self.assertRaises(InternalValidationError):
            assert_valid(data)

    def test_baseline_valid(self):
        self.assertEqual(validate_package(self.good), [])

    def test_mimetype_not_first(self):
        z = zipfile.ZipFile(io.BytesIO(self.good))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as o:
            for n in reversed(z.namelist()):
                o.writestr(n, z.read(n))
        self.assertTrue(any("mimetype" in p for p in validate_package(buf.getvalue())))

    def test_not_well_formed(self):
        self.bad(lambda p: p.__setitem__("Contents/section0.xml", p["Contents/section0.xml"][:-6]), "well-formed")

    def test_item_cnt_mismatch(self):
        self.bad(sub_part("Contents/header.xml", r'<hh:paraProperties itemCnt="(\d+)"',
                          lambda m: f'<hh:paraProperties itemCnt="{int(m.group(1)) + 1}"'), "itemCnt")

    def test_dangling_para_pr(self):
        self.bad(sub_part("Contents/section0.xml", r'paraPrIDRef="\d+"', 'paraPrIDRef="999"'), "paraPrIDRef")

    def test_dangling_char_pr(self):
        self.bad(sub_part("Contents/section0.xml", r'charPrIDRef="\d+"', 'charPrIDRef="999"'), "charPrIDRef")

    def test_dangling_binary_ref(self):
        self.bad(sub_part("Contents/section0.xml", r'binaryItemIDRef="image1"', 'binaryItemIDRef="image9"'), "binaryItemIDRef")

    def test_manifest_without_file(self):
        self.bad(lambda p: p.pop("BinData/image1.png"), "zip에 없음")

    def test_file_without_manifest(self):
        self.bad(lambda p: p.__setitem__("BinData/stray.png", b"x"), "manifest에 등록되지 않음")

    def test_equation_size_not_zero(self):
        self.bad(sub_part("Contents/section0.xml", r'(<hp:equation [^>]*>)<hp:sz width="0"', r'\1<hp:sz width="5"'), "sz")

    def test_duplicate_pic_id(self):
        two = run([prob(T("가"), figures=[{"id": "f1", "clean_ref": "a"}, {"id": "f2", "clean_ref": "b"}])]).hwpx_bytes

        def dup(parts):
            s = parts["Contents/section0.xml"].decode("utf-8")
            ids = re.findall(r'<hp:pic id="(\d+)"', s)
            parts["Contents/section0.xml"] = s.replace(f'<hp:pic id="{ids[1]}"', f'<hp:pic id="{ids[0]}"', 1).encode("utf-8")
        problems = validate_package(mutate(two, dup))
        self.assertTrue(any("그림 id 중복" in p for p in problems), problems)


# ---------------------------------------------------------------- 속성 테스트 (hypothesis 없이 시드 고정 난수)
TEXTS = ["값은?", "A&B<C>D", "가나다라마바사 " * 6, "a\tb\nc\x01d", "x", "", "①②③ 보기", "한 줄"]
MATHS = ["f(x)=5x-1", r"\frac{3x+1}{x+1}", r"\sqrt{2x+a}", "x^2+y^2+6x-20y+1=0", r"\sum_{k=1}^{n}k^2",
         r"a\approx b", r"\text{속력}=\frac{\text{거리}}{\text{시간}}", "a_1+a_2+a_3+a_4+a_5+a_6+a_7+a_8+a_9"]


def rand_inlines(rnd, allow_math=True):
    out = []
    for _ in range(rnd.randint(1, 5)):
        if allow_math and rnd.random() < 0.4:
            out.append(M(rnd.choice(MATHS)))
        else:
            out.append(T(rnd.choice(TEXTS), **({"bold": True} if rnd.random() < 0.1 else {})))
    return out


def rand_problem(rnd, k):
    c = {"stem": [{"type": "paragraph", "inlines": rand_inlines(rnd)} for _ in range(rnd.randint(0, 3))]}
    if rnd.random() < 0.7:
        c["choices"] = {"items": [rand_inlines(rnd) for _ in range(rnd.randint(0, 7))]}
    if rnd.random() < 0.4:
        c["figures"] = [{"id": f"f{j}", "clean_ref": rnd.choice(["a", "b", "zzz"]),
                         "placement": rnd.choice(["after_stem", "after_choices"]),
                         **({"width_mm": rnd.choice([10, 45, 120, 300])} if rnd.random() < 0.6 else {})}
                        for j in range(rnd.randint(1, 2))]
    return {"id": f"p{k}", "status": "confirmed" if rnd.random() < 0.9 else "needs_review", "content": c}


def rand_preset(rnd):
    return {"orientation": rnd.choice(["portrait", "landscape"]),
            "margins_mm": {"left": rnd.choice([5, 10, 20, 30]), "right": rnd.choice([5, 10, 20, 30]),
                           "gutter": rnd.choice([0, 0, 10])},
            "columns": {"count": rnd.randint(1, 3)},
            "typography": {"font_name": rnd.choice(["함초롬바탕", "맑은 고딕"]), "font_size_pt": rnd.choice([8, 10, 12, 14]),
                           "line_spacing_pct": rnd.choice([100, 130, 160, 200]),
                           "align": rnd.choice(["auto", "left", "justify"])},
            "numbering": {"format": "{n:02d}", "start": rnd.randint(1, 20)}}


class Property(unittest.TestCase):
    def test_random_exports_always_validate(self):
        ok = skipped = 0
        for seed in range(120):
            rnd = random.Random(seed)
            probs = [rand_problem(rnd, k) for k in range(rnd.randint(1, 8))]
            preset = rand_preset(rnd)
            try:
                r = run(probs, preset)
            except EmptyExportError:
                skipped += 1
                continue
            ok += 1
            self.assertEqual(validate_package(r.hwpx_bytes), [], f"seed={seed}")
            json.dumps(r.report.to_dict(), ensure_ascii=False)
            if seed % 10 == 0:  # 결정적 출력
                self.assertEqual(r.hwpx_bytes, run(probs, preset).hwpx_bytes, f"seed={seed}")
            # 제외된 문항(미확정·그림 없음) 수만큼만 줄고, 번호는 건너뛰지 않는다
            excluded = len(items_of(r, "NOT_CONFIRMED")) + len({i.problem_id for i in items_of(r, "FIGURE_MISSING")})
            self.assertEqual(r.report.stats["problems"], len(probs) - excluded, f"seed={seed}")
        self.assertGreater(ok, 80)  # 대부분은 실제로 내보내져야 의미가 있다
