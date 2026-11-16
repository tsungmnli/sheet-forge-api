"""B5-3c-2: 작업자의 사용량 기록 연결. DB 없이 도는 단위 테스트."""
import inspect
import unittest
from unittest import mock

from app.recognition import usage
from app.recognition.usage import record_job_usage
from app.worker import main as worker_main
from app.worker import problems as worker_problems


def _job():
    return mock.Mock(id="job_1", owner_id="o1", kind="problem_read", target_id="prob_1")


class RecordJobUsageTest(unittest.TestCase):
    def _db(self, session):
        db = mock.Mock()
        db.session.return_value.__enter__ = mock.Mock(return_value=session)
        db.session.return_value.__exit__ = mock.Mock(return_value=False)
        return db

    def test_records_rows_and_commits(self):
        added = []
        session = mock.Mock(add=added.append)
        record_job_usage(self._db(session), _job(),
                         [{"call": "read", "model": "m", "input_tokens": 5}, {"call": "repair", "model": "m"}])
        self.assertEqual([a.call for a in added], ["read", "repair"])
        self.assertEqual({(a.owner_id, a.job_kind, a.target_id) for a in added}, {("o1", "problem_read", "prob_1")})
        session.commit.assert_called_once()

    def test_no_events_does_not_open_session(self):
        db = mock.Mock()
        record_job_usage(db, _job(), None)
        record_job_usage(db, _job(), [])
        db.session.assert_not_called()

    def test_failure_is_swallowed_and_logs_only_kind(self):
        db = mock.Mock()
        db.session.side_effect = RuntimeError("비밀 내용 포함 메시지")
        with self.assertLogs("sheet_forge.worker", level="WARNING") as cm:
            record_job_usage(db, _job(), [{"call": "read", "model": "m"}])   # 예외를 올리지 않는다
        self.assertIn("RuntimeError", cm.output[0])
        self.assertNotIn("비밀", cm.output[0])


class WiringTest(unittest.TestCase):
    def test_handlers_call_record_job_usage_right_after_llm(self):
        read_src = inspect.getsource(worker_problems.handle_problem_read)
        self.assertLess(read_src.index("recognizer.read("), read_src.index("record_job_usage("))
        self.assertLess(read_src.index("record_job_usage("), read_src.index("normalize_read_content("))
        page_src = inspect.getsource(worker_main.handle_page_process)
        self.assertLess(page_src.index("processor.process("), page_src.index("record_job_usage("))
        self.assertIn('llm_event("segment"', page_src)

    def test_module_exports(self):
        self.assertTrue(callable(usage.record_job_usage))


if __name__ == "__main__":
    unittest.main()
