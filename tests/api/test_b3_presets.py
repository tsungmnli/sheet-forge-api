"""B3 3a단계: 저장된 모양 + 문제지 preset_id. DB 통합 테스트는 SHEET_FORGE_TEST_DATABASE_URL이 있을 때만 돈다.
복사 위치: tests/test_b3_presets.py"""
import copy
import os
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.main import create_app
from app.api.preset_service import builtin_presets
from app.api.settings import Settings
from app.db.database import Database
from app.export.hwpx import ExportPreset, plan_layout
from app.storage.images import MemoryImageStore

TEST_URL = os.environ.get("SHEET_FORGE_TEST_DATABASE_URL", "")
ROOT = Path(__file__).resolve().parent.parent.parent


def H(v):
    return {"If-Match": f'"{v}"'}


class UnitTest(unittest.TestCase):
    def test_builtins_are_valid(self):
        items = builtin_presets()
        self.assertEqual([i["name"] for i in items], ["A4 한 칸", "B5 두 칸"])
        for i in items:
            self.assertTrue(i["builtin"])
            plan_layout(ExportPreset.from_dict(i["preset"]))
        b5 = items[1]["preset"]
        self.assertEqual((b5["paper"]["kind"], b5["columns"]["count"]), ("B5", 2))

    def test_openapi_has_preset_routes(self):
        paths = create_app(Settings()).openapi()["paths"]
        self.assertIn("get", paths["/export-presets"])
        self.assertIn("post", paths["/export-presets"])
        self.assertIn("put", paths["/export-presets/{preset_id}"])
        self.assertIn("delete", paths["/export-presets/{preset_id}"])
        self.assertIn("/export-presets/defaults", paths)   # 기존 경로가 그대로 있다


@unittest.skipUnless(TEST_URL, "SHEET_FORGE_TEST_DATABASE_URL 없음 (DB 통합 테스트 건너뜀)")
class PresetFlowTest(unittest.TestCase):
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
            s.execute(text("TRUNCATE worksheet_items, worksheets, export_presets CASCADE"))
            s.commit()
        self.c = self._client()

    def _client(self, owner="o1"):
        return TestClient(create_app(Settings(database_url=TEST_URL, default_owner_id=owner),
                                     store=MemoryImageStore()))

    def _default(self):
        return self.c.get("/export-presets/defaults").json()["preset"]

    def test_list_create_update_delete(self):
        items = self.c.get("/export-presets").json()["items"]
        self.assertEqual([(i["builtin"], i["name"]) for i in items], [(True, "A4 한 칸"), (True, "B5 두 칸")])
        value = self._default()
        value["typography"]["font_size_pt"] = 12
        r = self.c.post("/export-presets", json={"name": "크게", "preset": value})
        self.assertEqual(r.status_code, 201, r.text)
        mine = r.json()
        self.assertEqual((mine["builtin"], mine["name"], mine["preset"]["typography"]["font_size_pt"]),
                         (False, "크게", 12))
        self.assertEqual(r.headers["ETag"], f'"{mine["version"]}"')
        self.assertEqual([i["name"] for i in self.c.get("/export-presets").json()["items"]],
                         ["A4 한 칸", "B5 두 칸", "크게"])
        bad = copy.deepcopy(value)
        bad["columns"]["count"] = 9
        r = self.c.post("/export-presets", json={"name": "나쁨", "preset": bad})
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (422, "PRESET_INVALID"))
        self.assertEqual(self.c.post("/export-presets", json={"name": " ", "preset": value}).status_code, 422)
        url = f"/export-presets/{mine['id']}"
        r = self.c.put(url, json={"name": "아주 크게", "preset": value}, headers=H(mine["version"]))
        self.assertEqual((r.status_code, r.json()["name"]), (200, "아주 크게"))
        self.assertGreater(r.json()["version"], mine["version"])
        self.assertEqual(self.c.put(url, json={"name": "x", "preset": value}, headers=H(mine["version"])).status_code, 412)
        self.assertEqual(self.c.put(url, json={"name": "x", "preset": value}).status_code, 428)
        self.assertEqual(self.c.put("/export-presets/builtin_a4_1col", json={"name": "x", "preset": value},
                                    headers=H(1)).status_code, 409)
        self.assertEqual(self.c.delete("/export-presets/builtin_b5_2col").status_code, 409)
        self.assertEqual(self.c.delete(url).status_code, 204)
        self.assertEqual(self.c.delete(url).status_code, 404)
        self.assertEqual(len(self.c.get("/export-presets").json()["items"]), 2)

    def test_owner_isolation(self):
        value = self._default()
        mine = self.c.post("/export-presets", json={"name": "내 것", "preset": value}).json()
        other = self._client(owner="o2")
        self.assertEqual(len(other.get("/export-presets").json()["items"]), 2)   # 내장 모양만
        self.assertEqual(other.delete(f"/export-presets/{mine['id']}").status_code, 404)

    def test_worksheet_preset_id_copies_value(self):
        ws = self.c.post("/worksheets", json={}).json()
        url = f"/worksheets/{ws['id']}"
        r = self.c.patch(url, json={"preset_id": "builtin_b5_2col"}, headers=H(ws["version"]))
        self.assertEqual(r.status_code, 200, r.text)
        got = r.json()
        self.assertEqual((got["preset"]["paper"]["kind"], got["preset"]["columns"]["count"]), ("B5", 2))
        self.assertLess(got["layout"]["col_w"], got["layout"]["body_w"])
        value = self._default()
        value["typography"]["font_size_pt"] = 12
        mine = self.c.post("/export-presets", json={"name": "크게", "preset": value}).json()
        r = self.c.patch(url, json={"preset_id": mine["id"]}, headers=H(got["version"]))
        self.assertEqual(r.json()["preset"]["typography"]["font_size_pt"], 12)
        v = r.json()["version"]
        self.assertEqual(self.c.delete(f"/export-presets/{mine['id']}").status_code, 204)   # 지워도 복사본은 그대로
        self.assertEqual(self.c.get(url).json()["preset"]["typography"]["font_size_pt"], 12)
        self.assertEqual(self.c.patch(url, json={"preset_id": mine["id"]}, headers=H(v)).status_code, 404)
        self.assertEqual(self.c.patch(url, json={"preset_id": "preset_nope"}, headers=H(v)).status_code, 404)
        both = self.c.patch(url, json={"preset_id": "builtin_a4_1col", "preset": value}, headers=H(v))
        self.assertEqual(both.status_code, 422)


if __name__ == "__main__":
    unittest.main()
