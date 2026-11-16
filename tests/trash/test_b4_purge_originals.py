"""B4-6c: 원본 사진 보존 기간 (DB 통합 테스트)."""
import unittest
from datetime import datetime, timezone

from sqlalchemy import text

from app.purge import purge_originals
from tests.api.test_b2 import make_png
from tests.trash.test_b4_trash_list import TEST_URL, TrashListTest as _Base


@unittest.skipUnless(TEST_URL, "SHEET_FORGE_TEST_DATABASE_URL 없음 (DB 통합 테스트 건너뜀)")
class PurgeOriginalsTest(_Base):
    def _setup_pages(self):
        """사진 3장: p1 40일 전·보정본 있음, p2 10일 전·보정본 있음, p3 40일 전·보정본 없음."""
        exam_id, _, _ = self._exam(0)
        files = [("files", ("p.png", make_png(40, 30), "image/png"))] * 2
        self.assertEqual(self.c.post(f"/v1/exams/{exam_id}/pages", files=files).status_code, 202)
        with self.db.session() as s:
            rows = s.execute(text("SELECT id, original_ref FROM pages ORDER BY position")).all()
            spec = [(40, "img_c1"), (10, "img_c2"), (40, None)]
            for (pid, _), (days, corr) in zip(rows, spec):
                if corr:
                    self.store.put(corr, b"c", "image/png")
                s.execute(text("UPDATE pages SET created_at = now() - make_interval(days => :d), corrected_ref = :c WHERE id = :i"),
                          {"d": days, "c": corr, "i": pid})
            s.commit()
        return exam_id, rows

    def _purge(self, days=30):
        with self.db.session() as s:
            return purge_originals(s, self.store, datetime.now(timezone.utc), days)

    def _original(self, pid):
        with self.db.session() as s:
            return s.execute(text("SELECT original_ref FROM pages WHERE id = :i"), {"i": pid}).scalar_one()

    def test_expired_original_only(self):
        _, rows = self._setup_pages()
        (p1, o1), (p2, o2), (p3, o3) = rows
        res = self._purge()
        self.assertEqual(res["pages"], 1)
        self.assertEqual(res["images"]["deleted"], 1)
        self.assertIsNone(self._original(p1))
        self.assertNotIn(o1, self.store.objects)
        self.assertIn("img_c1", self.store.objects)                       # 보정본은 남음
        self.assertEqual((self._original(p2), self._original(p3)), (o2, o3))   # 10일 전, 보정본 없는 것은 그대로
        detail = self.c.get(f"/v1/pages/{p1}").json()["image"]
        self.assertIsNone(detail["original_url"])
        self.assertTrue(detail["corrected_url"])
        self.assertEqual(self._purge()["pages"], 0)                       # 멱등
        # 설정을 7일로 줄이면 p2도 만료
        self.assertEqual(self.c.patch("/v1/me/settings", json={"original_photo_retention_days": 7}).status_code, 200)
        self.assertEqual(self._purge()["pages"], 1)
        self.assertIsNone(self._original(p2))

    def test_keep_forever_setting(self):
        _, rows = self._setup_pages()
        self.assertEqual(self.c.patch("/v1/me/settings", json={"original_photo_retention_days": 0}).status_code, 200)
        self.assertEqual(self._purge()["pages"], 0)
        self.assertEqual(self._original(rows[0][0]), rows[0][1])

    def test_same_object_original_is_skipped(self):
        exam_id, _, _ = self._exam(1)                                      # 가짜 처리기: 보정본 = 원본 객체
        with self.db.session() as s:
            s.execute(text("UPDATE pages SET created_at = now() - interval '90 days'"))
            s.commit()
        self.assertEqual(self._purge()["pages"], 0)


# 부모 클래스의 B4-2 테스트가 다시 돌지 않게 하고, 부모 클래스는 모듈에서 뺀다
PurgeOriginalsTest.test_exam_delete_lists_only_the_exam = None
PurgeOriginalsTest.test_independent_deletes_and_type_filter = None
PurgeOriginalsTest.test_owner_isolation = None
del _Base

if __name__ == "__main__":
    unittest.main()
