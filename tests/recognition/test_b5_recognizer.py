"""B5-3b-4a: RealRecognizer. 가짜 LlmClient·가짜 변환기를 쓴다."""
import io
import json
import unittest
from types import SimpleNamespace as NS

from PIL import Image

from app.recognition.llm.recognizer import ReadEmptyError, RealRecognizer
from app.recognition.llm.read import ReadParseError
from app.recognition.ports import LlmError, LlmLimits, LlmResult


def png(w, h):
    out = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(out, "PNG")
    return out.getvalue()


def conv(latex):
    return NS(ok=not latex.startswith("BAD"), error="오류", error_pos=0, warnings=[])


def read_json(*inl, choices=None):
    return json.dumps({"stem": [{"inlines": list(inl)}], "choices": choices, "figures": [], "uncertain": [],
                       "unsupported_block": None})


def T(v):
    return {"t": "text", "v": v, "latex": None}


def M(s):
    return {"t": "math", "v": None, "latex": s}


class FakeClient:
    def __init__(self, *outputs):
        self.outputs, self.calls = list(outputs), []

    def generate(self, model, image, prompt, schema, limits):
        self.calls.append((model, image, prompt, schema, limits))
        o = self.outputs.pop(0)
        if isinstance(o, Exception):
            raise o
        return LlmResult(text=o, model=model, input_tokens=100, output_tokens=20, latency_ms=5)


def rec(client, **kw):
    return RealRecognizer(client, "lite", "flash", convert_fn=conv, **kw)


class FallbackTest(unittest.TestCase):
    """다시 읽기(상위 모델)가 일시적 오류로 실패하면 처음 읽기 모델로 한 번 더 읽는다."""

    def test_high_timeout_falls_back_to_default_model(self):
        c = FakeClient(LlmError("timeout"), read_json(T("값을 구하시오. ")))
        r = rec(c).read(png(600, 400), "high")
        self.assertEqual([call[0] for call in c.calls], ["flash", "lite"])      # 상위 → 처음 읽기 모델
        self.assertEqual(r.meta["fallback"], {"from_model": "flash", "reason": "timeout"})
        self.assertEqual((r.meta["model"], r.meta["tier"]), ("lite", "default"))   # 실제로 읽은 모델을 그대로 남긴다
        self.assertEqual(r.content["stem"][0]["inlines"], [{"t": "text", "v": "값을 구하시오. "}])

    def test_other_transient_kinds_also_fall_back(self):
        for kind in ("network", "server", "rate_limit"):
            c = FakeClient(LlmError(kind), read_json(T("값")))
            self.assertEqual(rec(c).read(png(600, 400), "high").meta["fallback"]["reason"], kind)

    def test_no_fallback_for_config_or_blocked_errors(self):
        for kind in ("auth", "bad_request", "blocked"):
            c = FakeClient(LlmError(kind), read_json(T("값")))
            with self.assertRaises(LlmError):
                rec(c).read(png(600, 400), "high")
            self.assertEqual(len(c.calls), 1)                                   # 다른 모델로 다시 부르지 않는다

    def test_no_fallback_for_default_tier_or_same_model(self):
        c = FakeClient(LlmError("timeout"), read_json(T("값")))
        with self.assertRaises(LlmError):
            rec(c).read(png(600, 400))                                          # 처음 읽기는 바꿀 모델이 없다
        self.assertEqual(len(c.calls), 1)
        c = FakeClient(LlmError("timeout"), read_json(T("값")))
        with self.assertRaises(LlmError):
            RealRecognizer(c, "same", convert_fn=conv).read(png(600, 400), "high")   # 상위·처음 모델이 같으면 소용없다
        self.assertEqual(len(c.calls), 1)

    def test_fallback_failure_is_raised(self):
        c = FakeClient(LlmError("timeout"), LlmError("timeout"))
        with self.assertRaises(LlmError):
            rec(c).read(png(600, 400), "high")
        self.assertEqual([call[0] for call in c.calls], ["flash", "lite"])      # 한 번만 바꿔 본다


class ReadTest(unittest.TestCase):
    def test_happy_path_content_and_meta(self):
        c = FakeClient(read_json(T("값을 구하시오. "), M("1+2"), choices=[{"inlines": [M("3")]}]))
        r = rec(c).read(png(600, 400))
        self.assertEqual(len(c.calls), 1)
        self.assertEqual(r.content["stem"][0], {"type": "paragraph", "inlines": [
            {"t": "text", "v": "값을 구하시오. "}, {"t": "math", "latex": "1+2"}]})
        self.assertEqual(r.content["choices"], {"items": [[{"t": "math", "latex": "3"}]], "layout": "auto"})
        self.assertEqual(r.content["figures"], [])
        m = r.meta
        self.assertEqual((m["engine"], m["tier"], m["model"], m["prompt"], m["retried"]), ("llm", "default", "lite", "read_v5", False))
        self.assertEqual((m["math_repaired"], m["math_failed"], m["math_warnings"]), (0, [], []))
        self.assertEqual([u["call"] for u in m["usage"]], ["read"])
        self.assertNotIn("값을", json.dumps(m, ensure_ascii=False))

    def test_repair_replaces_bad_math(self):
        c = FakeClient(read_json(T("값을 구하시오. "), M("BAD1")), json.dumps({"fixes": [{"id": 0, "latex": "GOOD1"}]}))
        r = rec(c).read(png(600, 400))
        self.assertEqual(len(c.calls), 2)
        self.assertIsNone(c.calls[1][1])                       # 수리 호출은 이미지 없음
        self.assertEqual(r.content["stem"][0]["inlines"][1], {"t": "math", "latex": "GOOD1"})
        self.assertEqual((r.meta["math_repaired"], r.meta["math_failed"], r.meta["repair_prompt"]), (1, [], "repair_v1"))
        self.assertEqual([u["call"] for u in r.meta["usage"]], ["read", "repair"])

    def test_unrepaired_math_is_kept_and_listed_without_latex(self):
        c = FakeClient(read_json(T("값을 구하시오. "), M("BAD1")), json.dumps({"fixes": []}))
        r = rec(c).read(png(600, 400))
        self.assertEqual(r.content["stem"][0]["inlines"][1]["latex"], "BAD1")
        self.assertEqual(r.meta["math_failed"], [{"area": "stem", "para": 0, "inline": 1, "error_pos": 0}])
        self.assertNotIn("BAD1", json.dumps(r.meta))

    def test_repair_call_failure_does_not_fail_read(self):
        c = FakeClient(read_json(T("값을 구하시오. "), M("BAD1")), LlmError("rate_limit", 429))
        r = rec(c).read(png(600, 400))
        self.assertEqual((r.meta["repair_error"], len(r.meta["math_failed"])), ("rate_limit", 1))
        self.assertEqual([u["call"] for u in r.meta["usage"]], ["read"])

    def test_parse_error_retries_once_then_raises(self):
        c = FakeClient("그냥 글", read_json(T("값을 구하시오.")))
        r = rec(c).read(png(600, 400))
        self.assertEqual((len(c.calls), r.meta["retried"]), (2, True))
        with self.assertRaises(ReadParseError):
            rec(FakeClient("글", "글")).read(png(600, 400))

    def test_llm_error_propagates_and_empty_fails(self):
        with self.assertRaises(LlmError):
            rec(FakeClient(LlmError("auth", 401))).read(png(600, 400))
        with self.assertRaises(ReadEmptyError):
            rec(FakeClient(read_json(T("  ")))).read(png(600, 400))

    def test_high_tier_uses_high_model_and_bigger_crop(self):
        big = png(1600, 800)
        c1, c2 = FakeClient(read_json(T("값을 구하시오."))), FakeClient(read_json(T("값을 구하시오.")))
        rec(c1).read(big)
        r = rec(c2).read(big, "high")
        self.assertEqual((c1.calls[0][0], c2.calls[0][0], r.meta["tier"], r.meta["model"]), ("lite", "flash", "high", "flash"))
        self.assertEqual(max(Image.open(io.BytesIO(c1.calls[0][1])).size), 1000)
        self.assertEqual(max(Image.open(io.BytesIO(c2.calls[0][1])).size), 1400)

    def test_limits_pass_through_and_repair_keeps_extra(self):
        lim = LlmLimits(max_output_tokens=3000, generation_extra={"thinkingConfig": {"thinkingBudget": 0}})
        c = FakeClient(read_json(T("값을 구하시오. "), M("BAD1")), json.dumps({"fixes": []}))
        rec(c, limits=lim).read(png(600, 400))
        self.assertEqual(c.calls[0][4], lim)
        self.assertEqual(c.calls[1][4].generation_extra, lim.generation_extra)
        self.assertEqual(c.calls[1][4].max_output_tokens, 2000)


if __name__ == "__main__":
    unittest.main()
