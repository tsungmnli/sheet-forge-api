"""B5-3b-4b-1: build_recognizer·thinking_extra·high_limits."""
import io
import json
import unittest

from PIL import Image

from app.api.settings import Settings
from app.recognition.factory import READ_MAX_OUTPUT, build_recognizer, thinking_extra
from app.recognition.fake import FakeRecognizer
from app.recognition.llm.recognizer import RealRecognizer
from app.recognition.ports import LlmResult


class FakeClient:
    def __init__(self):
        self.calls = []

    def generate(self, model, image, prompt, schema, limits):
        self.calls.append((model, limits))
        text = json.dumps({"stem": [{"inlines": [{"t": "text", "v": "값을 구하시오.", "latex": None}]}], "choices": None,
                           "figures": [], "uncertain": [], "unsupported_block": None})
        return LlmResult(text=text, model=model)


def png():
    out = io.BytesIO()
    Image.new("RGB", (300, 200), "white").save(out, "PNG")
    return out.getvalue()


class ThinkingTest(unittest.TestCase):
    def test_by_model_family(self):
        self.assertEqual(thinking_extra("gemini-3.5-flash-lite"), {"thinkingConfig": {"thinkingLevel": "minimal"}})
        self.assertEqual(thinking_extra("gemini-3.5-flash"), {"thinkingConfig": {"thinkingLevel": "minimal"}})
        self.assertEqual(thinking_extra("gemini-3.8-flash"), {"thinkingConfig": {"thinkingBudget": 0}})


class BuildTest(unittest.TestCase):
    def test_fake_is_default(self):
        self.assertIsInstance(build_recognizer(Settings()), FakeRecognizer)

    def test_bad_engine_and_missing_key(self):
        with self.assertRaises(SystemExit):
            build_recognizer(Settings(recognition_engine="gemini"))
        with self.assertRaises(SystemExit):
            build_recognizer(Settings(recognition_engine="real"))

    def test_real_uses_settings_and_per_model_limits(self):
        c = FakeClient()
        r = build_recognizer(Settings(recognition_engine="real", llm_api_key="k", llm_timeout_s=20), client=c)
        self.assertIsInstance(r, RealRecognizer)
        self.assertEqual((r.model, r.high_model), ("gemini-3.5-flash-lite", "gemini-3.8-flash"))
        self.assertEqual((r.limits.max_output_tokens, r.limits.timeout_s), (READ_MAX_OUTPUT, 20.0))
        r.read(png())
        r.read(png(), "high")
        (m1, l1), (m2, l2) = c.calls
        self.assertEqual((m1, m2), ("gemini-3.5-flash-lite", "gemini-3.8-flash"))
        self.assertEqual(l1.generation_extra, {"thinkingConfig": {"thinkingLevel": "minimal"}})
        self.assertEqual(l2.generation_extra, {"thinkingConfig": {"thinkingBudget": 0}})

    def test_high_limits_default_to_limits(self):
        c = FakeClient()
        r = RealRecognizer(c, "a", "b")
        self.assertIsNone(r.high_limits)
        from app.recognition.ports import LlmLimits
        lim = LlmLimits(max_output_tokens=123)
        self.assertEqual(RealRecognizer(c, "a", "b", limits=lim).high_limits, lim)


if __name__ == "__main__":
    unittest.main()
