"""B5-2c: RealPageProcessor와 build_processor (합성 사진, 가짜 LlmClient. 네트워크·DB 없음)."""
import io
import json
import unittest

import numpy as np
from PIL import Image

from app.api.settings import Settings
from app.recognition.factory import build_processor
from app.recognition.fake import FakePageProcessor
from app.recognition.ports import LlmError, LlmResult
from app.recognition.processor import RealPageProcessor
from app.recognition.vision.decode import DecodeError


def photo():
    g = np.full((1200, 1600), 255, np.uint8)
    for y in range(200, 1000, 40):
        g[y:y + 14, 150:1450] = 0
    out = io.BytesIO()
    Image.fromarray(g).convert("RGB").save(out, "JPEG", quality=90)
    return out.getvalue()


class FakeClient:
    def __init__(self, text=None, error=None):
        self.text, self.error = text, error

    def generate(self, model, image, prompt, schema, limits):
        if self.error:
            raise self.error
        return LlmResult(text=self.text, model=model, input_tokens=1700, output_tokens=300)


ONE = json.dumps({"problems": [{"number": "1", "box_2d": [150, 80, 850, 920],
                                "choices_box_2d": None, "figure_box_2d": None}]})


class ProcessorTest(unittest.TestCase):
    def test_applies_correction_request(self):
        r = RealPageProcessor(FakeClient(ONE), "m").process(photo(), "image/jpeg", correction={"mode": "none"})
        self.assertEqual((r.width, r.height), (1600, 1200))
        self.assertEqual(r.applied["corners"], [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])
        auto = RealPageProcessor(FakeClient(ONE), "m").process(photo(), "image/jpeg")
        self.assertIn("found", auto.applied)

    def test_success_returns_corrected_jpeg_size_and_segments(self):
        r = RealPageProcessor(FakeClient(ONE), "m").process(photo(), "image/jpeg")
        im = Image.open(io.BytesIO(r.corrected))
        self.assertEqual((im.format, im.size), ("JPEG", (r.width, r.height)))
        self.assertEqual(r.corrected_content_type, "image/jpeg")
        self.assertEqual([s.number for s in r.segments], ["1"])
        self.assertIsNone(r.message)
        self.assertIsNone(r.fallback_reason)
        self.assertEqual(r.usage.input_tokens, 1700)

    def test_llm_failure_falls_back_with_message(self):
        r = RealPageProcessor(FakeClient(error=LlmError("timeout")), "m").process(photo(), "image/jpeg")
        self.assertGreaterEqual(len(r.segments), 1)
        self.assertEqual(r.fallback_reason, "llm_error:timeout")
        self.assertIn("네모를 직접", r.message)
        self.assertIsNone(r.usage)

    def test_undecodable_photo_raises(self):
        with self.assertRaises(DecodeError):
            RealPageProcessor(FakeClient(ONE), "m").process(b"not an image", "image/jpeg")


class FactoryTest(unittest.TestCase):
    def test_default_is_fake(self):
        self.assertIsInstance(build_processor(Settings()), FakePageProcessor)

    def test_env_parsing(self):
        s = Settings.from_env({"SHEET_FORGE_RECOGNITION_ENGINE": "REAL", "SHEET_FORGE_SEGMENT_IMAGE_LONG_SIDE": "1200"})
        self.assertEqual((s.recognition_engine, s.segment_image_long_side), ("real", 1200))
        self.assertEqual(Settings.from_env({}).segment_image_long_side, 1500)

    def test_real_needs_key_and_builds_with_settings(self):
        with self.assertRaises(SystemExit):
            build_processor(Settings(recognition_engine="real"))
        with self.assertRaises(SystemExit):
            build_processor(Settings(recognition_engine="gemini"))
        p = build_processor(Settings(recognition_engine="real", llm_api_key="k", segment_image_long_side=1200))
        self.assertIsInstance(p, RealPageProcessor)
        self.assertEqual((p.model, p.long_side), (Settings().segment_model, 1200))
        self.assertEqual(p.limits.timeout_s, 30.0)


if __name__ == "__main__":
    unittest.main()
