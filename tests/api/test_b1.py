"""B1: 시험지·사진 API, 작업 큐·작업자, 이미지 저장소. DB 통합 테스트는 SHEET_FORGE_TEST_DATABASE_URL이 있을 때만 돈다."""
import os
import struct
import unittest
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient
from sqlalchemy import text

from app import jobs
from app.api.errors import ApiError
from app.api.main import create_app
from app.api.pagination import decode_cursor, encode_cursor
from app.api.photos import sniff_image
from app.api.serialize import iso, next_action
from app.api.settings import Settings
from app.db.database import Database
from app.recognition.fake import FakePageProcessor
from app.storage.images import MemoryImageStore
from app.worker.main import PAGE_FAILED_MESSAGE, run_once

TEST_URL = os.environ.get("SHEET_FORGE_TEST_DATABASE_URL", "")
ROOT = Path(__file__).resolve().parent.parent.parent


def make_png(w=40, h=30):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    rows = b"".join(b"\x00" + bytes((200, 200, 220)) * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


class UnitTest(unittest.TestCase):
    def test_sniff_image(self):
        self.assertEqual(sniff_image(make_png()), "image/png")
        self.assertEqual(sniff_image(b"\xff\xd8\xff\xe0" + b"0" * 20), "image/jpeg")
        self.assertEqual(sniff_image(b"RIFF\x00\x00\x00\x00WEBPVP8 "), "image/webp")
        self.assertEqual(sniff_image(b"\x00\x00\x00\x18ftypheic" + b"0" * 8), "image/heic")
        self.assertIsNone(sniff_image(b"hello world, not an image"))
        self.assertIsNone(sniff_image(b""))

    def test_cursor_roundtrip_and_garbage(self):
        dt = datetime(2026, 11, 16, 1, 2, 3, 456789, tzinfo=timezone.utc)
        self.assertEqual(decode_cursor(encode_cursor(dt, "exam_X")), (dt, "exam_X"))
        with self.assertRaises(ApiError) as cm:
            decode_cursor("not-a-cursor")
        self.assertEqual((cm.exception.status, cm.exception.code), (400, "REQUEST_INVALID"))

    def test_next_action(self):
        self.assertEqual(next_action(0, 0, 0, 0, 0), "upload")
        self.assertEqual(next_action(2, 0, 0, 0, 0), "pick")
        self.assertEqual(next_action(2, 3, 3, 0, 0), "read")
        self.assertEqual(next_action(2, 3, 0, 2, 1), "review")
        self.assertEqual(next_action(2, 3, 0, 0, 3), "worksheet")

    def test_iso_is_utc_z(self):
        self.assertEqual(iso(datetime(2026, 11, 16, 9, 0, tzinfo=timezone(timedelta(hours=9)))), "2026-11-16T00:00:00Z")

    def test_fake_processor(self):
        r = FakePageProcessor().process(make_png(40, 30), "image/png")
        self.assertEqual((r.width, r.height), (40, 30))
        self.assertEqual([s.number for s in r.segments], ["01", "02", "03", "04", "05", "06"])
        for s in r.segments:
            x0, y0, x1, y1 = s.bbox
            self.assertTrue(0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1)

    def test_memory_store(self):
        st = MemoryImageStore()
        st.put("img_A", b"abc", "image/png")
        self.assertEqual(st.get("img_A"), (b"abc", "image/png"))
        st.delete("img_A")
        self.assertIsNone(st.get("img_A"))

    def test_photo_api_is_503_without_store(self):
        c = TestClient(create_app(Settings()))
        r = c.post("/exams/exam_X/pages", files=[("files", ("a.png", make_png(), "image/png"))])
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (503, "STORAGE_UNAVAILABLE"))

    def test_openapi_builds(self):
        paths = create_app(Settings()).openapi()["paths"]
        for p in ("/exams", "/exams/{exam_id}", "/exams/{exam_id}/pages", "/exams/{exam_id}/pages/order",
                  "/pages/{page_id}", "/images/{ref}"):
            self.assertIn(p, paths)


class Boom:
    def process(self, data, content_type, correction=None):
        raise RuntimeError("boom")


@unittest.skipUnless(TEST_URL, "SHEET_FORGE_TEST_DATABASE_URL 없음 (DB 통합 테스트 건너뜀)")
class FlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from alembic import command
        from alembic.config import Config
        cfg = Config(str(ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(ROOT / "migrations"))
        with mock.patch.dict(os.environ, {"SHEET_FORGE_DATABASE_URL": TEST_URL}):
            command.upgrade(cfg, "head")
        cls.db = Database(TEST_URL, "", 2, 3)

    @classmethod
    def tearDownClass(cls):
        cls.db.dispose()

    def setUp(self):
        with self.db.session() as s:
            s.execute(text("TRUNCATE jobs, segments, pages, exams CASCADE"))
            s.commit()
        self.store = MemoryImageStore()
        self.c = self._client()

    def _client(self, owner="o1", **settings):
        return TestClient(create_app(Settings(database_url=TEST_URL, default_owner_id=owner, **settings), store=self.store))

    def _exam(self, **body):
        r = self.c.post("/exams", json=body)
        self.assertEqual(r.status_code, 201)
        return r.json()

    def _upload(self, exam_id, n=1, c=None):
        files = [("files", (f"p{i}.png", make_png(40, 30), "image/png")) for i in range(n)]
        return (c or self.c).post(f"/exams/{exam_id}/pages", files=files)

    def _work(self, n):
        for _ in range(n):
            self.assertTrue(run_once(self.db, self.store, FakePageProcessor()))

    def test_exam_crud_and_optimistic_lock(self):
        r = self.c.post("/exams", json={})
        self.assertEqual(r.status_code, 201)
        e = r.json()
        self.assertEqual((e["title"], e["version"], e["next_action"], e["page_count"]), ("", 1, "upload", 0))
        self.assertEqual(r.headers["ETag"], '"1"')
        url = f"/exams/{e['id']}"
        self.assertEqual(self.c.patch(url, json={"title": "중간고사"}).status_code, 428)
        ok = self.c.patch(url, json={"title": "중간고사", "student": "민수"}, headers={"If-Match": '"1"'})
        self.assertEqual((ok.status_code, ok.json()["version"], ok.json()["title"]), (200, 2, "중간고사"))
        stale = self.c.patch(url, json={"title": "x"}, headers={"If-Match": '"1"'})
        self.assertEqual((stale.status_code, stale.json()["error"]["code"]), (412, "VERSION_CONFLICT"))
        self.assertEqual(self.c.patch(url, json={}, headers={"If-Match": '"2"'}).status_code, 422)
        self.assertEqual(self.c.get(url).json()["student"], "민수")
        self.assertEqual(len(self.c.get("/exams", params={"q": "중간"}).json()["items"]), 1)
        self.assertEqual(len(self.c.get("/exams", params={"student": "철수"}).json()["items"]), 0)
        self.assertEqual(self.c.delete(url).status_code, 204)
        self.assertEqual(self.c.get(url).status_code, 404)
        self.assertEqual(self.c.get("/exams").json()["items"], [])

    def test_exam_list_pagination(self):
        ids = [self._exam(title=f"t{i}")["id"] for i in range(3)]
        first = self.c.get("/exams", params={"limit": 2}).json()
        self.assertEqual(len(first["items"]), 2)
        self.assertIsNotNone(first["next_cursor"])
        second = self.c.get("/exams", params={"limit": 2, "cursor": first["next_cursor"]}).json()
        self.assertEqual(len(second["items"]), 1)
        self.assertIsNone(second["next_cursor"])
        self.assertEqual(sorted(i["id"] for i in first["items"] + second["items"]), sorted(ids))

    def test_upload_then_worker_produces_segments(self):
        e = self._exam()
        r = self._upload(e["id"], 2)
        self.assertEqual(r.status_code, 202)
        body = r.json()
        self.assertEqual([p["order"] for p in body["items"]], [0, 1])
        self.assertEqual(body["items"][0]["processing"]["state"], "queued")
        self.assertEqual(body["poll_after_ms"], 2000)
        exam = self.c.get(f"/exams/{e['id']}").json()
        self.assertEqual((exam["page_count"], exam["next_action"], exam["poll_after_ms"]), (2, "pick", 2000))
        self._work(2)
        self.assertFalse(run_once(self.db, self.store, FakePageProcessor()))
        lst = self.c.get(f"/exams/{e['id']}/pages")
        self.assertEqual([p["processing"]["state"] for p in lst.json()["items"]], ["done", "done"])
        self.assertIsNone(lst.json()["poll_after_ms"])
        self.assertEqual(self.c.get(f"/exams/{e['id']}/pages", headers={"If-None-Match": lst.headers["ETag"]}).status_code, 304)
        pid = lst.json()["items"][0]["id"]
        detail = self.c.get(f"/pages/{pid}").json()
        self.assertEqual(len(detail["segments"]), 6)
        self.assertFalse(any(s["marked"] for s in detail["segments"]))
        self.assertEqual((detail["image"]["width"], detail["image"]["height"]), (40, 30))
        self.assertIsNotNone(detail["image"]["corrected_url"])
        # 응답의 URL은 바깥 접두어(/api)를 포함한다. Ingress가 떼므로 TestClient에서는 떼고 요청한다.
        self.assertTrue(detail["image"]["original_url"].startswith("/api/images/"))
        orig_path = detail["image"]["original_url"].removeprefix("/api")
        img = self.c.get(orig_path)
        self.assertEqual((img.status_code, img.headers["content-type"], img.content), (200, "image/png", make_png(40, 30)))
        self.assertEqual(self.c.get(orig_path, headers={"If-None-Match": img.headers["ETag"]}).status_code, 304)

    def test_upload_validation(self):
        e = self._exam()
        bad = self.c.post(f"/exams/{e['id']}/pages", files=[("files", ("a.txt", b"hello not image", "text/plain"))])
        self.assertEqual((bad.status_code, bad.json()["error"]["code"]), (415, "PHOTO_UNSUPPORTED"))
        big = self._client(max_photo_bytes=10)
        r = self._upload(e["id"], c=big)
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (413, "PHOTO_TOO_LARGE"))
        few = self._client(max_pages_per_exam=1)
        r = self._upload(e["id"], 2, c=few)
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (422, "TOO_MANY_PAGES"))
        self.assertEqual(self._upload("exam_nope").status_code, 404)
        self.assertEqual(self.c.get(f"/exams/{e['id']}/pages").json()["items"], [])  # 실패한 업로드는 남지 않는다

    def test_reorder_and_delete_page(self):
        e = self._exam()
        ids = [p["id"] for p in self._upload(e["id"], 3).json()["items"]]
        url = f"/exams/{e['id']}/pages/order"
        r = self.c.put(url, json={"page_ids": list(reversed(ids))})
        self.assertEqual([p["id"] for p in r.json()["items"]], list(reversed(ids)))
        self.assertEqual(self.c.put(url, json={"page_ids": ids[:2]}).status_code, 422)
        self.assertEqual(self.c.put(url, json={"page_ids": ids + ids[:1]}).status_code, 422)
        self.assertEqual(self.c.delete(f"/pages/{ids[1]}").status_code, 204)
        rest = self.c.get(f"/exams/{e['id']}/pages").json()["items"]
        self.assertEqual([p["id"] for p in rest], [ids[2], ids[0]])
        self.assertEqual([p["order"] for p in rest], [0, 1])
        self.assertEqual(self.c.get(f"/pages/{ids[1]}").status_code, 404)

    def test_owner_isolation_and_exam_delete_cascade(self):
        e = self._exam()
        pid = self._upload(e["id"]).json()["items"][0]["id"]
        self._work(1)
        orig = self.c.get(f"/pages/{pid}").json()["image"]["original_url"].removeprefix("/api")
        other = self._client(owner="o2")
        self.assertEqual(other.get(f"/exams/{e['id']}").status_code, 404)
        self.assertEqual(other.get(f"/pages/{pid}").status_code, 404)
        self.assertEqual(other.get(orig).status_code, 404)
        self.assertEqual(other.get("/exams").json()["items"], [])
        self.assertEqual(self.c.delete(f"/exams/{e['id']}").status_code, 204)
        self.assertEqual(self.c.get(f"/pages/{pid}").status_code, 404)
        self.assertEqual(self.c.get(orig).status_code, 404)

    def test_job_dedup_and_deleted_page_is_skipped(self):
        with self.db.session() as s:
            a = jobs.enqueue(s, "o1", "page_process", "page", "page_X")
            b = jobs.enqueue(s, "o1", "page_process", "page", "page_X")
            s.commit()
        self.assertEqual((a, b), (True, False))
        self.assertTrue(run_once(self.db, self.store, FakePageProcessor()))  # page_X는 없음 → 조용히 완료
        self.assertFalse(run_once(self.db, self.store, FakePageProcessor()))

    def test_worker_retries_then_marks_page_failed(self):
        e = self._exam()
        pid = self._upload(e["id"]).json()["items"][0]["id"]
        for _ in range(2):
            self.assertTrue(run_once(self.db, self.store, Boom(), retry_delay_s=0))
            self.assertEqual(self.c.get(f"/pages/{pid}").json()["processing"]["state"], "queued")
        self.assertTrue(run_once(self.db, self.store, Boom(), retry_delay_s=0))
        proc = self.c.get(f"/pages/{pid}").json()["processing"]
        self.assertEqual((proc["state"], proc["message"]), ("failed", PAGE_FAILED_MESSAGE))
        self.assertFalse(run_once(self.db, self.store, Boom(), retry_delay_s=0))


if __name__ == "__main__":
    unittest.main()
