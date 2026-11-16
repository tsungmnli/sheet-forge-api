"""B5-2b-4: 열 분할 폴백과 분할 오케스트레이터(합성 이미지, 가짜 LlmClient)."""
import io
import json
import unittest

import numpy as np
from PIL import Image

from app.recognition.ports import LlmError, LlmResult
from app.recognition.segmenter import detect_segments
from app.recognition.vision.segment_fallback import FALLBACK_MESSAGE, detect_columns


def page(blocks, size=1000):
    g = np.full((size, size), 255, np.uint8)
    for x0, x1, y0, y1 in blocks:
        for y in range(y0, y1, 24):
            g[y:y + 12, x0:x1] = 0
    return g


def png(g):
    out = io.BytesIO()
    Image.fromarray(g).save(out, "PNG")
    return out.getvalue()


TWO_COL = [(80, 470, 200, 800), (530, 920, 200, 800)]


class FakeClient:
    def __init__(self, text=None, error=None):
        self.text, self.error, self.calls = text, error, 0

    def generate(self, model, image, prompt, schema, limits):
        self.calls += 1
        if self.error:
            raise self.error
        return LlmResult(text=self.text, model=model, input_tokens=1700, output_tokens=300)


class FallbackTest(unittest.TestCase):
    def test_two_columns_make_two_boxes_left_first(self):
        a, b = detect_columns(page(TWO_COL))
        self.assertIsNone(a.number)
        self.assertLess(a.bbox[2], 0.5)
        self.assertGreater(b.bbox[0], 0.5)
        self.assertAlmostEqual(a.bbox[0], 0.075, delta=0.01)
        self.assertAlmostEqual(a.bbox[1], 0.195, delta=0.015)
        self.assertAlmostEqual(b.bbox[2], 0.925, delta=0.01)

    def test_single_column_makes_one_box(self):
        (s,) = detect_columns(page([(100, 900, 200, 800)]))
        self.assertLess(s.bbox[0], 0.11)
        self.assertGreater(s.bbox[2], 0.89)

    def test_header_does_not_hide_the_gutter(self):
        g = page(TWO_COL)
        g[40:52, 80:920] = 0          # 맨 위 안내문이 두 열에 걸쳐 있음
        self.assertEqual(len(detect_columns(g)), 2)

    def test_blank_page_gives_one_whole_page_box(self):
        (s,) = detect_columns(np.full((500, 500), 255, np.uint8))
        self.assertEqual(s.bbox, (0.0, 0.0, 1.0, 1.0))


class SegmenterTest(unittest.TestCase):
    def setUp(self):
        self.img = png(page(TWO_COL))

    def test_success_uses_llm_boxes_and_returns_usage(self):
        text = json.dumps({"problems": [{"number": "5", "box_2d": [200, 80, 800, 470],
                                         "choices_box_2d": None, "figure_box_2d": None}]})
        out = detect_segments(FakeClient(text), "m", self.img)
        self.assertEqual([s.number for s in out.segments], ["5"])
        self.assertIsNone(out.fallback_reason)
        self.assertIsNone(out.message)
        self.assertEqual(out.usage.input_tokens, 1700)

    def test_llm_error_falls_back(self):
        out = detect_segments(FakeClient(error=LlmError("rate_limit", 429)), "m", self.img)
        self.assertEqual(len(out.segments), 2)
        self.assertEqual((out.fallback_reason, out.message, out.usage), ("llm_error:rate_limit", FALLBACK_MESSAGE, None))

    def test_bad_output_falls_back(self):
        out = detect_segments(FakeClient("not json"), "m", self.img)
        self.assertEqual((out.fallback_reason, len(out.segments)), ("bad_output", 2))

    def test_zero_problems_falls_back_but_keeps_usage(self):
        out = detect_segments(FakeClient(json.dumps({"problems": []})), "m", self.img)
        self.assertEqual((out.fallback_reason, len(out.segments)), ("no_problems", 2))
        self.assertEqual(out.message, FALLBACK_MESSAGE)
        self.assertIsNotNone(out.usage)


if __name__ == "__main__":
    unittest.main()
