"""B4-4: 내 정보·설정."""
import unittest

from sqlalchemy import text
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.api.settings import Settings
from tests.trash.test_b4_trash_list import TEST_URL, TrashListTest as _Base


class UnitTest(unittest.TestCase):
    def test_me_without_db(self):
        c = TestClient(create_app(Settings(default_owner_id="o1")))
        self.assertEqual(c.get("/v1/me").json(), {"id": "o1", "display_name": "선생님"})


@unittest.skipUnless(TEST_URL, "SHEET_FORGE_TEST_DATABASE_URL 없음 (DB 통합 테스트 건너뜀)")
class MeSettingsTest(_Base):
    def setUp(self):
        super().setUp()
        with self.db.session() as s:
            s.execute(text("TRUNCATE user_settings"))
            s.commit()

    def test_defaults_and_partial_patch(self):
        r = self.c.get("/v1/me/settings")
        self.assertEqual(r.json(), {"font_scale": 100, "student_name_display": "full", "original_photo_retention_days": 30,
                                    "default_preset_id": None, "auto_next_after_confirm": True})
        r = self.c.patch("/v1/me/settings", json={"font_scale": 130, "original_photo_retention_days": 0})
        self.assertEqual((r.status_code, r.json()["font_scale"], r.json()["original_photo_retention_days"]), (200, 130, 0))
        r = self.c.patch("/v1/me/settings", json={"student_name_display": "masked", "auto_next_after_confirm": False})
        body = r.json()
        self.assertEqual((body["font_scale"], body["student_name_display"], body["auto_next_after_confirm"]), (130, "masked", False))
        self.assertEqual(self.c.get("/v1/me/settings").json(), body)

    def test_invalid_values(self):
        for bad in ({"font_scale": 99}, {"student_name_display": "x"}, {"original_photo_retention_days": 15},
                    {"auto_next_after_confirm": None}, {"font_scale": None}, {"unknown": 1}, {"default_preset_id": "preset_nope"}):
            self.assertEqual(self.c.patch("/v1/me/settings", json=bad).status_code, 422, bad)
        self.assertEqual(self.c.get("/v1/me/settings").json()["font_scale"], 100)   # 거절된 요청은 저장되지 않음

    def test_default_preset_and_isolation(self):
        r = self.c.patch("/v1/me/settings", json={"default_preset_id": "builtin_b5_2col"})
        self.assertEqual(r.json()["default_preset_id"], "builtin_b5_2col")
        other = TestClient(create_app(Settings(database_url=TEST_URL, default_owner_id="o2"), store=self.store))
        self.assertIsNone(other.get("/v1/me/settings").json()["default_preset_id"])
        r = self.c.patch("/v1/me/settings", json={"default_preset_id": None})
        self.assertIsNone(r.json()["default_preset_id"])


# 부모 클래스의 B4-2 테스트가 다시 돌지 않게 하고, 부모 클래스는 모듈에서 뺀다
MeSettingsTest.test_exam_delete_lists_only_the_exam = None
MeSettingsTest.test_independent_deletes_and_type_filter = None
MeSettingsTest.test_owner_isolation = None
del _Base

if __name__ == "__main__":
    unittest.main()
