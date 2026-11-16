"""B3 3b단계: 문제 검색 + 문제지 점검. DB 통합 테스트는 SHEET_FORGE_TEST_DATABASE_URL이 있을 때만 돈다.
복사 위치: tests/test_b3_tools.py"""
import os
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient
from sqlalchemy import text

import tests.api.test_b3 as b3
from app.api.main import create_app
from app.api.settings import Settings
from app.api.worksheet_tools import figure_missing
from app.db.database import Database
from app.storage.images import MemoryImageStore

TEST_URL = os.environ.get("SHEET_FORGE_TEST_DATABASE_URL", "")
ROOT = Path(__file__).resolve().parent.parent.parent
H = b3.H


class UnitTest(unittest.TestCase):
    def test_figure_missing(self):
        self.assertFalse(figure_missing({}))
        self.assertFalse(figure_missing({"figures": [{"use": "clean", "clean_ref": "a", "raw_ref": None}]}))
        self.assertTrue(figure_missing({"figures": [{"use": "clean", "clean_ref": None, "raw_ref": "b"}]}))
        self.assertFalse(figure_missing({"figures": [{"use": "raw", "clean_ref": None, "raw_ref": "b"}]}))
        self.assertTrue(figure_missing({"figures": [{"raw_ref": "b"}]}))   # use 기본값은 clean

    def test_openapi_has_tools_routes(self):
        paths = create_app(Settings()).openapi()["paths"]
        self.assertIn("get", paths["/v1/problems"])
        self.assertIn("/v1/problems/{pid}", paths)                          # 기존 경로와 공존
        self.assertIn("/v1/worksheets/{worksheet_id}/check", paths)


@unittest.skipUnless(TEST_URL, "SHEET_FORGE_TEST_DATABASE_URL 없음 (DB 통합 테스트 건너뜀)")
class ToolsFlowTest(unittest.TestCase):
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

    _client = b3.WorksheetFlowTest._client
    _exam = b3.WorksheetFlowTest._exam
    _ws = b3.WorksheetFlowTest._ws

    def _search(self, qs=""):
        r = self.c.get(f"/v1/problems{qs}")
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_search_filters(self):
        exam_id, ids = self._exam()                    # 3개 읽음, 앞 2개 확인 완료
        got = self._search()
        self.assertEqual({i["id"] for i in got["items"]}, set(ids[:2]))      # 기본은 확인 완료
        item = got["items"][0]
        self.assertEqual((item["exam"]["id"], item["exam"]["student"], item["status"]), (exam_id, "민수", "confirmed"))
        self.assertFalse(item["in_worksheet"])
        self.assertEqual([i["id"] for i in self._search("?status=needs_review")["items"]], [ids[2]])
        self.assertEqual(len(self._search("?student=민수")["items"]), 2)
        self.assertEqual(self._search("?student=없는학생")["items"], [])
        self.assertEqual(len(self._search(f"?exam_id={exam_id}")["items"]), 2)
        word = item["preview"].split()[0][:2]
        self.assertTrue(word)
        self.assertIn(item["id"], [i["id"] for i in self._search(f"?q={word}")["items"]])
        self.assertEqual(self._search("?q=zzzzqqqq")["items"], [])
        self.assertEqual(self.c.get("/v1/problems?status=bogus").status_code, 422)

    def test_search_in_worksheet_paging_owner_deleted(self):
        exam_id, ids = self._exam()
        ws = self._ws(problem_ids=[ids[0]])
        got = self._search(f"?worksheet_id={ws['id']}")["items"]
        self.assertEqual({i["id"]: i["in_worksheet"] for i in got}, {ids[0]: True, ids[1]: False})
        self.assertEqual(self.c.get("/v1/problems?worksheet_id=ws_nope").status_code, 404)
        page1 = self._search("?limit=1")
        self.assertEqual(len(page1["items"]), 1)
        page2 = self._search(f"?limit=1&cursor={page1['next_cursor']}")
        self.assertEqual(len(page2["items"]), 1)
        self.assertNotEqual(page1["items"][0]["id"], page2["items"][0]["id"])
        self.assertEqual(self._client(owner="o2").get("/v1/problems").json()["items"], [])
        self.assertEqual(self.c.delete(f"/v1/problems/{ids[0]}").status_code, 204)
        self.assertEqual([i["id"] for i in self._search()["items"]], [ids[1]])     # 지운 문제는 안 나온다

    def test_check(self):
        exam_id, ids = self._exam()
        empty = self._ws()
        r = self.c.get(f"/v1/worksheets/{empty['id']}/check").json()
        self.assertEqual((r["ready"], [i["code"] for i in r["items"]]), (False, ["EMPTY_EXPORT"]))
        ws = self._ws(from_exam_id=exam_id)
        r = self.c.get(f"/v1/worksheets/{ws['id']}/check").json()
        self.assertEqual((r["ready"], r["items"]), (True, []))
        added = self.c.post(f"/v1/worksheets/{ws['id']}/problems", json={"problem_ids": [ids[2]]}).json()
        r = self.c.get(f"/v1/worksheets/{ws['id']}/check").json()
        self.assertTrue(r["ready"])
        self.assertEqual([(i["code"], i["severity"], i["problem_ids"]) for i in r["items"]],
                         [("UNCONFIRMED", "warn", [ids[2]])])
        self.assertEqual(self.c.patch(f"/v1/worksheets/{ws['id']}", json={"unconfirmed_policy": "fail"},
                                      headers=H(added["version"])).status_code, 200)
        r = self.c.get(f"/v1/worksheets/{ws['id']}/check").json()
        self.assertEqual((r["ready"], [i["code"] for i in r["items"]]), (False, ["UNCONFIRMED_BLOCKS"]))
        self.assertEqual(self.c.delete(f"/v1/problems/{ids[0]}").status_code, 204)
        v = self.c.get(f"/v1/worksheets/{ws['id']}").json()["version"]
        self.assertEqual(self.c.patch(f"/v1/worksheets/{ws['id']}", json={"unconfirmed_policy": "skip"},
                                      headers=H(v)).status_code, 200)
        r = self.c.get(f"/v1/worksheets/{ws['id']}/check").json()
        self.assertEqual((r["ready"], sorted(i["code"] for i in r["items"])), (True, ["DELETED", "UNCONFIRMED"]))
        self.assertEqual(self._client(owner="o2").get(f"/v1/worksheets/{ws['id']}/check").status_code, 404)


if __name__ == "__main__":
    unittest.main()
