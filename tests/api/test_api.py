"""A1~A3: 엔드포인트 계약, 오류 매핑, 결정성, 로그 비노출 (설계 9장). fastapi·httpx2 필요."""
import base64
import json
import struct
import unittest
import zlib
from datetime import datetime, timezone
from unittest import mock

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.api.service import safe_filename
from app.api.settings import Settings
from app.export.hwpx import InternalValidationError
from app.export.hwpx.validate import validate_package

FIXED = datetime(2026, 11, 15, 0, 0, 0, tzinfo=timezone.utc)


def make_png(w=40, h=30):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    rows = b"".join(b"\x00" + bytes((200, 200, 220)) * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


B64 = lambda b: base64.b64encode(b).decode("ascii")


def prob(pid="p1", text="값은?", status="confirmed", figures=None, items=None):
    c = {"stem": [{"type": "paragraph", "inlines": [{"t": "text", "v": text}, {"t": "math", "latex": "x^2+1"}]}]}
    if figures is not None:
        c["figures"] = figures
    if items is not None:
        c["choices"] = {"items": [[{"t": "text", "v": x}] for x in items]}
    return {"id": pid, "status": status, "content": c}


def client(settings=None):
    return TestClient(create_app(settings or Settings(), clock=lambda: FIXED))


def err(r):
    return r.json()["error"]


class Health(unittest.TestCase):
    def test_healthz_and_readyz(self):
        c = client()
        self.assertEqual(c.get("/healthz").json(), {"status": "ok"})
        r = c.get("/readyz")
        self.assertEqual((r.status_code, r.json()["checks"]), (200, {"template": True}))

    def test_readyz_unavailable_when_a_check_fails(self):
        app = create_app(Settings(), clock=lambda: FIXED)
        app.state.readiness_checks["db"] = lambda: (_ for _ in ()).throw(OSError("down"))
        r = TestClient(app).get("/readyz")
        self.assertEqual((r.status_code, r.json()["status"], r.json()["checks"]["db"]), (503, "unavailable", False))
        self.assertEqual(TestClient(app).get("/healthz").status_code, 200)  # liveness는 영향 없음


class LayoutAndDefaults(unittest.TestCase):
    def test_layout_preview(self):
        r = client().post("/exports/layout-preview", json={"preset": {"columns": {"count": 3}}})
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertEqual(j["effective_preset"]["columns"]["count"], 3)
        self.assertGreater(j["layout"]["body_w"], j["layout"]["col_w"])

    def test_layout_preview_default_and_golden(self):
        j = client().post("/exports/layout-preview", json={}).json()
        self.assertEqual(j["layout"]["body_w"], j["layout"]["col_w"])  # 1단

    def test_layout_preview_invalid_preset(self):
        r = client().post("/exports/layout-preview", json={"preset": {"columns": {"count": 9}}})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(err(r)["code"], "PRESET_INVALID")
        self.assertIn("PRESET_COLUMNS", [d["code"] for d in err(r)["details"]])

    def test_defaults(self):
        j = client().get("/export-presets/defaults").json()
        self.assertEqual(j["preset"]["orientation"], "portrait")
        self.assertEqual([p["kind"] for p in j["papers"]], ["A4", "B5"])


class ExportJson(unittest.TestCase):
    def post(self, c=None, **kw):
        body = {"title": "시험 1", "problems": [prob()], **kw}
        return (c or client()).post("/exports", json=body)

    def test_happy_path_and_file_is_valid(self):
        r = self.post(preset={"columns": {"count": 2}})
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertEqual(set(j), {"report", "file"})
        data = base64.b64decode(j["file"]["content_base64"])
        self.assertEqual(len(data), j["file"]["size"])
        self.assertEqual(j["file"]["name"], "시험_1.hwpx")
        self.assertEqual(validate_package(data), [])
        self.assertEqual(j["report"]["effective_preset"]["columns"]["count"], 2)
        self.assertEqual(j["report"]["stats"]["problems"], 1)

    def test_deterministic_with_fixed_clock(self):
        self.assertEqual(self.post().json()["file"]["content_base64"], self.post().json()["file"]["content_base64"])

    def test_images_and_figures(self):
        p = prob(figures=[{"id": "f", "clean_ref": "a", "width_mm": 45}])
        r = self.post(problems=[p], images={"a": B64(make_png())})
        self.assertEqual(r.json()["report"]["stats"]["figures"], 1)
        self.assertEqual(validate_package(base64.b64decode(r.json()["file"]["content_base64"])), [])

    def test_unknown_fields_pass_through_and_missing_image_is_report_not_error(self):
        p = prob("a")
        p["ocr"] = {"engine": "x"}
        q = prob("b", figures=[{"id": "f", "clean_ref": "nope"}])
        r = self.post(problems=[p, q])
        self.assertEqual(r.status_code, 200)
        codes = [i["code"] for i in r.json()["report"]["items"]]
        self.assertIn("FIGURE_MISSING", codes)
        self.assertEqual(r.json()["report"]["stats"]["problems"], 1)

    def test_request_id(self):
        c = client()
        r = c.post("/exports", json={"problems": [prob()]}, headers={"X-Request-Id": "abc-123"})
        self.assertEqual(r.headers["X-Request-Id"], "abc-123")
        r = c.get("/healthz", headers={"X-Request-Id": "bad id!"})
        self.assertNotEqual(r.headers["X-Request-Id"], "bad id!")
        self.assertTrue(r.headers["X-Request-Id"])
        r = c.post("/exports", json={"problems": []}, headers={"X-Request-Id": "rid-9"})
        self.assertEqual(err(r)["request_id"], "rid-9")

    def test_logs_contain_no_content(self):
        secret = "비밀문항텍스트"
        with self.assertLogs("sheet_forge.api", level="INFO") as cm:
            self.post(problems=[prob(text=secret)], title="홍길동 시험")
        out = "\n".join(cm.output)
        self.assertNotIn(secret, out)
        self.assertNotIn("홍길동", out)
        self.assertIn('"event": "export"', out)


class ExportBinary(unittest.TestCase):
    def test_hwpx_format(self):
        r = client().post("/exports?format=hwpx", json={"title": "중간고사 1학년", "problems": [prob()]})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers["content-type"].startswith("application/vnd.hancom.hwpx"))
        self.assertIn("filename*=UTF-8''", r.headers["content-disposition"])
        self.assertEqual(r.headers["x-export-status"], "ok")
        self.assertEqual((r.headers["x-export-warnings"], r.headers["x-export-errors"]), ("0", "0"))
        self.assertEqual(validate_package(r.content), [])

    def test_bad_format_value(self):
        r = client().post("/exports?format=docx", json={"problems": [prob()]})
        self.assertEqual((r.status_code, err(r)["code"]), (422, "REQUEST_INVALID"))


class ErrorMapping(unittest.TestCase):
    def test_empty_export(self):
        r = client().post("/exports", json={"problems": []})
        self.assertEqual((r.status_code, err(r)["code"]), (422, "EMPTY_EXPORT"))
        r = client().post("/exports", json={"problems": [prob(status="needs_review")]})  # 전부 제외
        self.assertEqual((r.status_code, err(r)["code"]), (422, "EMPTY_EXPORT"))

    def test_invalid_preset(self):
        r = client().post("/exports", json={"problems": [prob()], "preset": {"typography": {"font_size_pt": 99}}})
        self.assertEqual((r.status_code, err(r)["code"]), (422, "PRESET_INVALID"))
        self.assertIn("PRESET_FONT_SIZE", [d["code"] for d in err(r)["details"]])

    def test_unconfirmed_fail(self):
        r = client().post("/exports", json={"problems": [prob(status="needs_review")], "preset": {"on_unconfirmed": "fail"}})
        self.assertEqual((r.status_code, err(r)["code"]), (409, "NOT_CONFIRMED"))

    def test_request_shape(self):
        c = client()
        for body in ({"problems": "x"}, {"problems": [{"id": "p"}]}, {"problems": [prob()], "bogus": 1},
                     {"problems": [{"id": "p", "content": {"stem": "text"}}]},
                     {"problems": [{"id": "p", "content": {"stem": [{"inlines": [{"v": "x"}]}]}}]}):
            r = c.post("/exports", json=body)
            self.assertEqual((r.status_code, err(r)["code"]), (422, "REQUEST_INVALID"), body)
            self.assertTrue(err(r)["details"])

    def test_limits(self):
        c = client(Settings(max_problems=2, max_figures=1))
        r = c.post("/exports", json={"problems": [prob(f"p{i}") for i in range(3)]})
        self.assertEqual((r.status_code, err(r)["code"]), (413, "TOO_MANY_PROBLEMS"))
        fig = [{"id": "f", "clean_ref": "a"}]
        r = c.post("/exports", json={"problems": [prob("a", figures=fig), prob("b", figures=fig)]})
        self.assertEqual((r.status_code, err(r)["code"]), (413, "TOO_MANY_FIGURES"))

    def test_image_errors(self):
        c = client(Settings(max_image_bytes=200, max_image_px=100))
        big = {"problems": [prob()], "images": {"a": B64(make_png(400, 300) + b"x" * 300)}}
        self.assertEqual((c.post("/exports", json=big).status_code), 413)
        px = {"problems": [prob()], "images": {"a": B64(make_png(150, 10))}}
        r = c.post("/exports", json=px)
        self.assertEqual((r.status_code, err(r)["code"]), (413, "PAYLOAD_TOO_LARGE"))
        for bad, code in (("@@not base64@@", "IMAGE_INVALID"), (B64(b"GIF89a" + b"0" * 30), "IMAGE_INVALID")):
            r = c.post("/exports", json={"problems": [prob()], "images": {"a": bad}})
            self.assertEqual((r.status_code, err(r)["code"]), (422, code))

    def test_body_too_large_by_content_length(self):
        c = client(Settings(max_body_bytes=100))
        r = c.post("/exports", json={"problems": [prob()]})
        self.assertEqual((r.status_code, err(r)["code"]), (413, "PAYLOAD_TOO_LARGE"))
        self.assertIn("X-Request-Id", r.headers)

    def test_internal_error_returns_no_file_and_hides_details(self):
        with mock.patch("app.api.service.export_hwpx", side_effect=InternalValidationError(["secret detail"])):
            with self.assertLogs("sheet_forge.api", level="ERROR"):
                r = client().post("/exports", json={"problems": [prob()]})
        self.assertEqual((r.status_code, err(r)["code"]), (500, "INTERNAL_ERROR"))
        self.assertNotIn("secret detail", r.text)

    def test_unknown_route(self):
        r = client().get("/nope")
        self.assertEqual((r.status_code, err(r)["code"]), (404, "HTTP_404"))


class Filename(unittest.TestCase):
    def test_safe_filename(self):
        self.assertEqual(safe_filename('a/b:c*?"<>|  d'), "abc_d.hwpx")
        self.assertEqual(safe_filename(""), "시험지.hwpx")
        self.assertEqual(safe_filename("..."), "시험지.hwpx")
        self.assertEqual(safe_filename("중간고사 1학년 3반"), "중간고사_1학년_3반.hwpx")
        self.assertLessEqual(len(safe_filename("가" * 300)), 125)
        self.assertNotIn("\n", safe_filename("a\nb"))


if __name__ == "__main__":
    unittest.main()
