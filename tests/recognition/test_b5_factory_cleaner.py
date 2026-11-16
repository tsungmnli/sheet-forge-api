"""B5-4c: 그림 정리기 선택(fake | real). DB 없이 도는 단위 테스트."""
import inspect
import unittest
from unittest import mock

from app.recognition.factory import build_cleaner
from app.recognition.fake import FakeFigureCleaner
from app.recognition.vision.figure_clean import FigureCleaner
from app.worker import main as worker_main


class BuildCleanerTest(unittest.TestCase):
    def test_default_is_fake(self):
        for engine in ("fake", "", None, " FAKE "):
            self.assertIsInstance(build_cleaner(mock.Mock(recognition_engine=engine)), FakeFigureCleaner)

    def test_real_needs_no_llm_key(self):
        c = build_cleaner(mock.Mock(recognition_engine="real", llm_api_key=""))
        self.assertIsInstance(c, FigureCleaner)

    def test_unknown_engine_exits(self):
        with self.assertRaises(SystemExit):
            build_cleaner(mock.Mock(recognition_engine="bogus"))


class WiringTest(unittest.TestCase):
    def test_worker_main_uses_build_cleaner(self):
        src = inspect.getsource(worker_main.main)
        self.assertIn("build_cleaner(settings)", src)
        self.assertNotIn("FakeFigureCleaner()", src)


if __name__ == "__main__":
    unittest.main()
