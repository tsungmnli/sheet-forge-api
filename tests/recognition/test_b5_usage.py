"""B5-3c-1: 사용량 기록. 단위 테스트 + (SHEET_FORGE_TEST_DATABASE_URL이 있을 때만) DB 통합 테스트."""
import os
import unittest
from pathlib import Path
from unittest import mock

from sqlalchemy import select, text

from app.db.models import UsageEvent
from app.recognition.ports import LlmResult
from app.recognition.usage import llm_event, record_usage

TEST_URL = os.environ.get("SHEET_FORGE_TEST_DATABASE_URL", "")
ROOT = Path(__file__).resolve().parent.parent.parent


class UnitTest(unittest.TestCase):
    def test_llm_event_from_result(self):
        r = LlmResult(text="비밀 내용", model="m-from-result", input_tokens=10, output_tokens=20, thinking_tokens=3, latency_ms=45)
        e = llm_event("segment", "", r)
        self.assertEqual(e, {"call": "segment", "model": "m-from-result", "input_tokens": 10, "output_tokens": 20,
                             "thinking_tokens": 3, "latency_ms": 45})
        self.assertEqual(llm_event("read", "given", r)["model"], "given")
        self.assertNotIn("비밀", str(e))

    def test_record_usage_adds_rows_without_commit(self):
        added = []
        session = mock.Mock(add=added.append)
        n = record_usage(session, "o1", "problem_read", "prob_1",
                         [{"call": "read", "model": "m", "input_tokens": 5}, {"call": "repair", "model": "m", "output_tokens": None}])
        self.assertEqual(n, 2)
        self.assertEqual([(a.call, a.input_tokens, a.output_tokens, a.thinking_tokens, a.latency_ms) for a in added],
                         [("read", 5, 0, 0, 0), ("repair", 0, 0, 0, 0)])
        self.assertEqual({(a.owner_id, a.job_kind, a.target_id) for a in added}, {("o1", "problem_read", "prob_1")})
        session.commit.assert_not_called()
        self.assertEqual(record_usage(session, "o1", "problem_read", "prob_1", None), 0)


@unittest.skipUnless(TEST_URL, "SHEET_FORGE_TEST_DATABASE_URL 없음 (DB 통합 테스트 건너뜀)")
class DbTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from alembic import command
        from alembic.config import Config
        from app.db.database import Database
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
            s.execute(text("DELETE FROM usage_events WHERE target_id LIKE 'prob_usage_test%'"))
            s.commit()

    def test_rows_are_saved(self):
        events = [{"call": "read", "model": "m1", "input_tokens": 1700, "output_tokens": 500, "thinking_tokens": 0, "latency_ms": 900},
                  {"call": "repair", "model": "m1", "input_tokens": 300, "output_tokens": 40, "thinking_tokens": 0, "latency_ms": 200}]
        with self.db.session() as s:
            record_usage(s, "o1", "problem_read", "prob_usage_test1", events)
            s.commit()
        with self.db.session() as s:
            rows = s.execute(select(UsageEvent).where(UsageEvent.target_id == "prob_usage_test1").order_by(UsageEvent.id)).scalars().all()
            self.assertEqual([(r.call, r.model, r.input_tokens, r.output_tokens, r.latency_ms) for r in rows],
                             [("read", "m1", 1700, 500, 900), ("repair", "m1", 300, 40, 200)])
            self.assertIsNotNone(rows[0].created_at)


if __name__ == "__main__":
    unittest.main()
