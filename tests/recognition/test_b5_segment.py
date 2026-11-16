"""B5-2b-2: 분할 호출(축소, 프롬프트·스키마 전달, 결과 변환, 오류 전파). 가짜 LlmClient를 쓴다."""
import io
import json
import unittest

from PIL import Image

from app.recognition.llm.schemas import SEGMENT_SCHEMA
from app.recognition.llm.segment import PROMPT_PATH, load_prompt, segment_page, shrink_for_segment
from app.recognition.ports import LlmError, LlmResult
from app.recognition.vision.segment_post import SegmentParseError


def png(w, h):
    out = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(out, "PNG")
    return out.getvalue()


class FakeClient:
    def __init__(self, text=None, error=None):
        self.text, self.error, self.calls = text, error, []

    def generate(self, model, image, prompt, schema, limits):
        self.calls.append((model, image, prompt, schema, limits))
        if self.error:
            raise self.error
        return LlmResult(text=self.text, model=model, input_tokens=1700, output_tokens=450)


ONE = json.dumps({"problems": [{"number": "3", "box_2d": [100, 50, 300, 480],
                                "choices_box_2d": None, "figure_box_2d": None}]})


class SegmentTest(unittest.TestCase):
    def test_prompt_file_is_the_confirmed_one(self):
        text = load_prompt()
        self.assertEqual(PROMPT_PATH.name, "segment_v2.md")
        for key in ("box_2d", "choices_box_2d", "figure_box_2d", "[ymin, xmin, ymax, xmax]"):
            self.assertIn(key, text)
        self.assertNotIn("\r", text)

    def test_shrinks_to_long_side_jpeg(self):
        im = Image.open(io.BytesIO(shrink_for_segment(png(3000, 2000), 1500)))
        self.assertEqual((im.format, im.size), ("JPEG", (1500, 1000)))
        small = Image.open(io.BytesIO(shrink_for_segment(png(800, 600), 1500)))
        self.assertEqual(small.size, (800, 600))

    def test_calls_client_once_and_returns_segments_and_usage(self):
        c = FakeClient(ONE)
        segs, usage = segment_page(c, "m-seg", png(3000, 2000))
        self.assertEqual(len(c.calls), 1)
        model, image, prompt, schema, limits = c.calls[0]
        self.assertEqual((model, prompt, schema), ("m-seg", load_prompt(), SEGMENT_SCHEMA))
        self.assertEqual(Image.open(io.BytesIO(image)).size, (1500, 1000))
        self.assertEqual(limits.temperature, 0.0)
        self.assertGreaterEqual(limits.max_output_tokens, 4000)
        self.assertEqual([(s.number, s.bbox) for s in segs], [("3", (0.05, 0.1, 0.48, 0.3))])
        self.assertEqual((usage.model, usage.input_tokens), ("m-seg", 1700))

    def test_zero_problems_gives_empty_list(self):
        segs, _ = segment_page(FakeClient(json.dumps({"problems": []})), "m", png(500, 500))
        self.assertEqual(segs, [])

    def test_errors_propagate(self):
        with self.assertRaises(LlmError):
            segment_page(FakeClient(error=LlmError("timeout")), "m", png(500, 500))
        with self.assertRaises(SegmentParseError):
            segment_page(FakeClient("not json"), "m", png(500, 500))

    def test_schema_requires_all_fields(self):
        item = SEGMENT_SCHEMA["properties"]["problems"]["items"]
        self.assertEqual(item["required"], ["number", "box_2d", "choices_box_2d", "figure_box_2d"])
        self.assertTrue(item["properties"]["choices_box_2d"]["nullable"])


if __name__ == "__main__":
    unittest.main()
