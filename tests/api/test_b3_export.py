"""B3 4단계: 문제지 내보내기(POST /v1/worksheets/{id}/export). DB 통합 테스트는 SHEET_FORGE_TEST_DATABASE_URL이 있을 때만 돈다.
복사 위치: tests/test_b3_export.py"""
import base64
import os
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.adapters.store_images import StoreImages
from app.api.main import create_app
from app.api.settings import Settings
from app.api.worksheet_export import add_links
from app.db.database import Database
from app.export.hwpx.images import load_image
from app.recognition.fake import FakeFigureCleaner, FakePageProcessor, FakeRecognizer
from app.storage.images import MemoryImageStore, StorageError
from app.worker.main import run_once
from tests.api.test_b2 import make_png

TEST_URL = os.environ.get("SHEET_FORGE_TEST_DATABASE_URL", "")
ROOT = Path(__file__).resolve().parent.parent.parent


def H(v):
    return {"If-Match": f'"{v}"'}


class UnitTest(unittest.TestCase):
    def test_add_links(self):
        rep = {"items": [{"code": "A", "problem_id": "p1"}, {"code": "B", "problem_id": None}, {"code": "C"},
                         {"code": "D", "problem_id": "zz"}]}
        out = add_links(rep, {"p1": "e1"})
        self.assertEqual(out["items"][0]["link"], {"exam_id": "e1", "problem_id": "p1"})
        for i in (1, 2, 3):
            self.assertNotIn("link", out["items"][i])

    def test_store_images(self):
        store = MemoryImageStore()
        store.put("ok", make_png(40, 30), "image/png")
        store.put("txt", b"hello", "image/png")
        store.put("wide", make_png(200, 10), "image/png")
        im = StoreImages(store, max_bytes=100000, max_px=100)
        img = im.get("ok")
        self.assertEqual((img.width_px, img.height_px), (40, 30))
        self.assertIsNone(im.get("nope"))
        self.assertEqual((im.get("txt").width_px, im.get("txt").height_px), (0, 0))   # PNG 검사가 보고하게 한다
        with self.assertRaises(ValueError):
            im.get("wide")                                    # 픽셀 한계 초과
        with self.assertRaises(ValueError):
            StoreImages(store, max_bytes=10, max_px=100).get("ok")   # 바이트 한계 초과
        store.delete("ok")
        self.assertIs(im.get("ok"), img)                      # 한 요청 안에서는 캐시

    def test_library_reports_storage_failures(self):
        class Broken:
            def get(self, ref):
                raise StorageError("down")
        img, why = load_image(StoreImages(Broken(), 10 ** 6, 1000), "r")
        self.assertIsNone(img)
        self.assertIn("불러오지 못함", why)
        store = MemoryImageStore()
        store.put("txt", b"hello", "image/png")
        img, why = load_image(StoreImages(store, 10 ** 6, 1000), "txt")
        self.assertEqual((img, why), (None, "PNG가 아님: txt"))
        img, why = load_image(StoreImages(store, 10 ** 6, 1000), "none")
        self.assertEqual((img, why), (None, "그림을 찾지 못함: none"))

    def test_openapi_has_export_route(self):
        self.assertIn("/v1/worksheets/{worksheet_id}/export", create_app(Settings()).openapi()["paths"])


@unittest.skipUnless(TEST_URL, "SHEET_FORGE_TEST_DATABASE_URL 없음 (DB 통합 테스트 건너뜀)")
class WorksheetExportFlowTest(unittest.TestCase):
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
            s.execute(text("TRUNCATE jobs, worksheet_items, worksheets, export_presets, problems, read_usage, "
                           "segments, pages, exams CASCADE"))
            s.commit()
        self.store = MemoryImageStore()

    def _client(self, owner="o1", **settings):
        return TestClient(create_app(Settings(database_url=TEST_URL, default_owner_id=owner, **settings),
                                     store=self.store))

    def _exam(self, n=3, confirm=2):
        """시험지 1건, 문제 n개를 읽고 앞에서 confirm개를 확인 완료. (exam_id, 문제 id 목록(사진 순서))"""
        c = self.c = self._client()
        exam = c.post("/v1/exams", json={"student": "민수"}).json()
        r = c.post(f"/v1/exams/{exam['id']}/pages", files=[("files", ("p.png", make_png(40, 30), "image/png"))])
        self.assertEqual(r.status_code, 202)
        page_id = r.json()["items"][0]["id"]
        self.assertTrue(run_once(self.db, self.store, FakePageProcessor(), recognizer=FakeRecognizer(),
                                 cleaner=FakeFigureCleaner()))
        for s in c.get(f"/v1/pages/{page_id}").json()["segments"][:n]:
            self.assertEqual(c.patch(f"/v1/pages/{page_id}/segments/{s['id']}", json={"marked": True}).status_code, 200)
        self.assertEqual(c.post(f"/v1/exams/{exam['id']}/read").status_code, 202)
        for _ in range(n):
            self.assertTrue(run_once(self.db, self.store, FakePageProcessor(), recognizer=FakeRecognizer(),
                                     cleaner=FakeFigureCleaner()))
        ids = [i["problem_id"] for i in c.get(f"/v1/exams/{exam['id']}/problems").json()["items"] if i["problem_id"]]
        self.assertEqual(len(ids), n)
        for pid in ids[:confirm]:
            v = c.get(f"/v1/problems/{pid}").json()["version"]
            r = c.post(f"/v1/problems/{pid}/confirm", headers=H(v))
            self.assertEqual(r.status_code, 200, r.text)
        return exam["id"], ids

    def _ws(self, **body):
        r = self.c.post("/v1/worksheets", json=body)
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    def test_export_json_records_last_export(self):
        exam_id, ids = self._exam(n=3, confirm=2)
        ws = self._ws(problem_ids=ids, title="오답 문제지")        # 세 번째는 확인 전
        self.assertIsNone(ws["last_export"])
        r = self.c.post(f"/v1/worksheets/{ws['id']}/export")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["report"]["stats"]["problems"], 2)
        skipped = [i for i in body["report"]["items"] if i["code"] == "NOT_CONFIRMED"]
        self.assertEqual([i["problem_id"] for i in skipped], [ids[2]])
        self.assertEqual(skipped[0]["link"], {"exam_id": exam_id, "problem_id": ids[2]})
        self.assertEqual(body["file"]["name"], "오답_문제지.hwpx")
        raw = base64.b64decode(body["file"]["content_base64"])
        self.assertEqual((raw[:2], len(raw)), (b"PK", body["file"]["size"]))
        after = self.c.get(f"/v1/worksheets/{ws['id']}").json()
        self.assertEqual(after["last_export"]["name"], "오답_문제지.hwpx")
        self.assertEqual(after["last_export"]["status"], body["report"]["status"])
        self.assertTrue(after["last_export"]["at"])
        self.assertEqual(after["version"], ws["version"])          # last_export 기록은 version을 올리지 않는다

    def test_export_hwpx_binary(self):
        _, ids = self._exam(n=3, confirm=2)
        ws = self._ws(problem_ids=ids[:2], title="오답 문제지")
        r = self.c.post(f"/v1/worksheets/{ws['id']}/export?format=hwpx")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.headers["content-type"].startswith("application/vnd.hancom.hwpx"))
        self.assertEqual(r.content[:2], b"PK")
        self.assertEqual(r.headers["X-Export-Errors"], "0")
        self.assertIn("X-Export-Status", r.headers)
        self.assertIn("export.hwpx", r.headers["content-disposition"])
        self.assertEqual(self.c.post(f"/v1/worksheets/{ws['id']}/export?format=docx").status_code, 422)

    def test_export_errors_do_not_record(self):
        _, ids = self._exam(n=3, confirm=2)
        empty = self._ws()
        r = self.c.post(f"/v1/worksheets/{empty['id']}/export")
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (422, "EMPTY_EXPORT"))
        self.assertIsNone(self.c.get(f"/v1/worksheets/{empty['id']}").json()["last_export"])
        self.assertEqual(self.c.post("/v1/worksheets/ws_nope/export").status_code, 404)
        ws = self._ws(problem_ids=ids[:1])
        self.assertEqual(self._client(owner="o2").post(f"/v1/worksheets/{ws['id']}/export").status_code, 404)

    def test_fail_policy_blocks_unconfirmed(self):
        _, ids = self._exam(n=3, confirm=2)
        ws = self._ws(problem_ids=ids)
        r = self.c.patch(f"/v1/worksheets/{ws['id']}", json={"unconfirmed_policy": "fail"}, headers=H(ws["version"]))
        self.assertEqual(r.status_code, 200, r.text)
        r = self.c.post(f"/v1/worksheets/{ws['id']}/export")
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (409, "NOT_CONFIRMED"))
        self.assertIsNone(self.c.get(f"/v1/worksheets/{ws['id']}").json()["last_export"])

    def test_too_many_problems(self):
        _, ids = self._exam(n=3, confirm=3)
        ws = self._ws(problem_ids=ids)
        r = self._client(max_problems=2).post(f"/v1/worksheets/{ws['id']}/export")
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (413, "TOO_MANY_PROBLEMS"))


if __name__ == "__main__":
    unittest.main()
