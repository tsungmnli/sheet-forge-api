"""B4-6b: 영구 삭제 뒤 이미지 객체 정리 (DB 통합 테스트)."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from sqlalchemy import text

from app.purge import delete_unreferenced_images, purge_trash_with_images
from app.storage.images import StorageError
from tests.trash.test_b4_trash_list import TEST_URL, TrashListTest as _Base


@unittest.skipUnless(TEST_URL, "SHEET_FORGE_TEST_DATABASE_URL 없음 (DB 통합 테스트 건너뜀)")
class PurgeImagesTest(_Base):
    def _age(self, days):
        with self.db.session() as s:
            for t in ("exams", "pages", "segments", "problems", "worksheets"):
                s.execute(text(f"UPDATE {t} SET deleted_at = now() - make_interval(days => :d) WHERE deleted_at IS NOT NULL"), {"d": days})
            s.commit()

    def test_purge_removes_only_purged_rows_images(self):
        exam1, _, _ = self._exam(2)
        gone = set(self.store.objects)
        self.assertTrue(gone)
        self._exam(1)
        kept = set(self.store.objects) - gone
        self.assertTrue(kept)
        self.assertEqual(self.c.delete(f"/exams/{exam1}").status_code, 204)
        self._age(31)
        with self.db.session() as s:
            res = purge_trash_with_images(s, self.store, datetime.now(timezone.utc) - timedelta(days=30))
        self.assertEqual(res["counts"]["exam"], 1)
        self.assertNotIn("refs", res)
        self.assertEqual(res["images"]["failed"], 0)
        self.assertEqual(set(self.store.objects) & gone, set())      # 지운 시험지의 이미지는 사라짐
        self.assertTrue(kept <= set(self.store.objects))             # 다른 시험지의 이미지는 그대로

    def test_still_referenced_is_kept_and_storage_errors_are_counted(self):
        self._exam(0)
        with self.db.session() as s:
            live = s.execute(text("SELECT original_ref FROM pages LIMIT 1")).scalar_one()
            self.store.put("img_orphan", b"x", "image/png")
            res = delete_unreferenced_images(s, self.store, [live, "img_orphan", "img_missing"])
        self.assertEqual(res, {"deleted": 2, "kept": 1, "failed": 0})
        self.assertIn(live, self.store.objects)
        self.assertNotIn("img_orphan", self.store.objects)
        with self.db.session() as s, mock.patch.object(self.store, "delete", side_effect=StorageError("x")):
            res = delete_unreferenced_images(s, self.store, ["img_orphan2"])
        self.assertEqual(res, {"deleted": 0, "kept": 0, "failed": 1})


# 부모 클래스의 B4-2 테스트가 다시 돌지 않게 하고, 부모 클래스는 모듈에서 뺀다
PurgeImagesTest.test_exam_delete_lists_only_the_exam = None
PurgeImagesTest.test_independent_deletes_and_type_filter = None
PurgeImagesTest.test_owner_isolation = None
del _Base

if __name__ == "__main__":
    unittest.main()
