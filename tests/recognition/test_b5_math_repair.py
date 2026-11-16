"""B5-3b-3: 수식 수리 호출. 가짜 LlmClient와 가짜 변환기를 쓴다."""
import copy
import json
import unittest
from types import SimpleNamespace as NS

from app.recognition.llm.math_repair import (PROMPT_PATH, REPAIR_SCHEMA, load_repair_prompt, repair_math)
from app.recognition.ports import LlmError, LlmResult


def M(s):
    return {"t": "math", "v": None, "latex": s}


def conv(latex):
    return NS(ok=latex.startswith("GOOD"))


class FakeClient:
    def __init__(self, text=None, error=None):
        self.text, self.error, self.calls = text, error, []

    def generate(self, model, image, prompt, schema, limits):
        self.calls.append((model, image, prompt, schema, limits))
        if self.error:
            raise self.error
        return LlmResult(text=self.text, model=model, input_tokens=300, output_tokens=40)


def setup():
    obj = {"stem": [{"inlines": [M("a1"), M("a2")]}], "choices": [{"inlines": [M("c1")]}]}
    failures = [
        {"area": "stem", "para": 0, "inline": 0, "latex": "a1", "error": "e1", "error_pos": 0},
        {"area": "stem", "para": 0, "inline": 1, "latex": "a2", "error": "e2", "error_pos": None},
        {"area": "choices", "para": 0, "inline": 0, "latex": "c1", "error": "e3", "error_pos": 1},
    ]
    return obj, failures


class PromptTest(unittest.TestCase):
    def test_file_has_placeholders_and_filled(self):
        raw = PROMPT_PATH.read_text(encoding="utf-8")
        self.assertEqual((raw.count("{{VOCAB}}"), raw.count("{{ITEMS}}")), (1, 1))
        text = load_repair_prompt([{"id": 0, "latex": "\\foo", "error": "x", "error_pos": 1}])
        self.assertNotIn("{{", text)
        self.assertIn('"latex": "\\\\foo"', text)


class RepairTest(unittest.TestCase):
    def test_no_failures_no_call(self):
        c = FakeClient("{}")
        obj, _ = setup()
        out = repair_math(c, "m", obj, [], convert_fn=conv)
        self.assertEqual((c.calls, out.fixed, out.remaining, out.usage, out.error_kind), ([], 0, [], None, None))

    def test_text_only_call_and_only_valid_fixes_replaced(self):
        obj, failures = setup()
        before = copy.deepcopy(obj)
        text = json.dumps({"fixes": [{"id": 0, "latex": "GOOD0"}, {"id": 1, "latex": "BAD"},
                                     {"id": 2, "latex": "GOOD2"}]})
        c = FakeClient(text)
        out = repair_math(c, "m", obj, failures, convert_fn=conv)
        model, image, prompt, schema, _ = c.calls[0]
        self.assertEqual((model, image, schema), ("m", None, REPAIR_SCHEMA))
        self.assertIn('"id": 2', prompt)
        self.assertEqual(out.fixed, 2)
        self.assertEqual(out.obj["stem"][0]["inlines"][0]["latex"], "GOOD0")
        self.assertEqual(out.obj["stem"][0]["inlines"][1]["latex"], "a2")
        self.assertEqual(out.obj["choices"][0]["inlines"][0]["latex"], "GOOD2")
        self.assertEqual([f["latex"] for f in out.remaining], ["a2"])
        self.assertEqual(out.usage.input_tokens, 300)
        self.assertEqual(obj, before)

    def test_bad_ids_unchanged_duplicates_ignored(self):
        obj, failures = setup()
        text = json.dumps({"fixes": [{"id": 9, "latex": "GOOD"}, {"id": -1, "latex": "GOOD"}, {"id": True, "latex": "GOOD"},
                                     {"id": 0, "latex": "a1"}, {"id": 0, "latex": "GOOD0"}, {"id": 0, "latex": "GOOD9"},
                                     "x", {"id": 1}]})
        out = repair_math(FakeClient(text), "m", obj, failures, convert_fn=conv)
        self.assertEqual(out.fixed, 1)
        self.assertEqual(out.obj["stem"][0]["inlines"][0]["latex"], "GOOD0")
        self.assertEqual(len(out.remaining), 2)

    def test_backslash_single_escape_is_recovered(self):
        obj, failures = setup()
        text = '{"fixes":[{"id":0,"latex":"GOOD\\frac{1}{2}"}]}'    # JSON에서 역슬래시 하나(\f 폼 피드가 되기 쉬운 경우)
        out = repair_math(FakeClient(text), "m", obj, failures, convert_fn=conv)
        self.assertEqual(out.obj["stem"][0]["inlines"][0]["latex"], "GOOD\\frac{1}{2}")

    def test_llm_error_and_bad_output_keep_everything(self):
        obj, failures = setup()
        out = repair_math(FakeClient(error=LlmError("rate_limit", 429)), "m", obj, failures, convert_fn=conv)
        self.assertEqual((out.obj, out.fixed, len(out.remaining), out.usage, out.error_kind), (obj, 0, 3, None, "rate_limit"))
        out = repair_math(FakeClient("그냥 글"), "m", obj, failures, convert_fn=conv)
        self.assertEqual((out.fixed, len(out.remaining), out.error_kind), (0, 3, "not_json"))
        self.assertIsNotNone(out.usage)
        out = repair_math(FakeClient('{"fixes": 3}'), "m", obj, failures, convert_fn=conv)
        self.assertEqual(out.error_kind, "bad_shape")


if __name__ == "__main__":
    unittest.main()
