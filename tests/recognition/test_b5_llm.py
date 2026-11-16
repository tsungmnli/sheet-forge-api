"""B5-2a: LLM 어댑터(요청 모양, 응답 해석, 재시도, 오류 종류, 키 비노출). 네트워크 없이 가짜 transport로 확인한다."""
import base64
import json
import unittest

from app.api.settings import Settings
from app.recognition.llm.client import GeminiClient
from app.recognition.ports import LlmError, LlmLimits

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 8
OK = {"candidates": [{"content": {"parts": [{"text": "{\"problems\": []}"}]}, "finishReason": "STOP"}],
      "usageMetadata": {"promptTokenCount": 1700, "candidatesTokenCount": 450, "thoughtsTokenCount": 0}}


class Script:
    """호출마다 (상태, 헤더, 본문)을 차례로 돌려주고 받은 요청을 기록한다."""

    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def __call__(self, url, headers, body, timeout):
        self.calls.append((url, headers, json.loads(body), timeout))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        status, headers_, data = r
        return status, headers_, data if isinstance(data, bytes) else json.dumps(data).encode()


class LlmClientTest(unittest.TestCase):
    def client(self, *responses, key="SECRET-KEY"):
        self.script, self.sleeps = Script(*responses), []
        return GeminiClient(key, transport=self.script, sleep=self.sleeps.append)

    def test_request_shape_and_result(self):
        c = self.client((200, {}, OK))
        schema = {"type": "object"}
        limits = LlmLimits(timeout_s=12, max_output_tokens=777, generation_extra={"thinkingConfig": {"thinkingBudget": 0}})
        r = c.generate("gemini-x", PNG, "프롬프트", schema, limits)
        url, headers, body, timeout = self.script.calls[0]
        self.assertTrue(url.endswith("/models/gemini-x:generateContent"))
        self.assertNotIn("SECRET-KEY", url)
        self.assertEqual(headers["x-goog-api-key"], "SECRET-KEY")
        self.assertEqual(timeout, 12)
        parts = body["contents"][0]["parts"]
        self.assertEqual(parts[0], {"text": "프롬프트"})
        self.assertEqual(parts[1]["inline_data"]["mime_type"], "image/png")
        self.assertEqual(base64.b64decode(parts[1]["inline_data"]["data"]), PNG)
        cfg = body["generationConfig"]
        self.assertEqual((cfg["temperature"], cfg["maxOutputTokens"], cfg["responseMimeType"]), (0.0, 777, "application/json"))
        self.assertEqual(cfg["responseSchema"], schema)
        self.assertEqual(cfg["thinkingConfig"], {"thinkingBudget": 0})
        self.assertEqual((r.text, r.model, r.input_tokens, r.output_tokens, r.finish_reason),
                         ("{\"problems\": []}", "gemini-x", 1700, 450, "STOP"))

    def test_thought_parts_are_not_in_text(self):
        data = {"candidates": [{"content": {"parts": [{"text": "생각", "thought": True}, {"text": "{}"}]}}],
                "usageMetadata": {"thoughtsTokenCount": 30}}
        r = self.client((200, {}, data)).generate("m", None, "p", None, LlmLimits())
        self.assertEqual((r.text, r.thinking_tokens), ("{}", 30))
        self.assertNotIn("inline_data", json.dumps(self.script.calls[0][2]))  # 이미지 없음

    def test_retry_429_then_success_and_retry_after(self):
        c = self.client((429, {"Retry-After": "3"}, b"{}"), (503, {}, b"{}"), (200, {}, OK))
        self.assertEqual(c.generate("m", None, "p", None, LlmLimits(retries=2)).input_tokens, 1700)
        self.assertEqual(self.sleeps, [3.0, 4.0])      # Retry-After, 그다음 기본 지연(2초 × 2번째)

    def test_retry_exhausted_and_no_retry_on_4xx(self):
        c = self.client((429, {}, b"{}"), (429, {}, b"{}"), (429, {}, b"{}"))
        with self.assertRaises(LlmError) as e:
            c.generate("m", None, "p", None, LlmLimits(retries=2))
        self.assertEqual((e.exception.kind, e.exception.status, len(self.script.calls)), ("rate_limit", 429, 3))
        c = self.client((400, {}, b"{\"error\": \"SECRET-KEY echoed\"}"))
        with self.assertRaises(LlmError) as e:
            c.generate("m", None, "p", None, LlmLimits())
        self.assertEqual((e.exception.kind, len(self.script.calls)), ("bad_request", 1))
        self.assertNotIn("SECRET", str(e.exception))     # 응답 본문·키는 메시지에 없다
        for status, kind in ((401, "auth"), (403, "auth"), (500, "server")):
            with self.assertRaises(LlmError) as e:
                self.client((status, {}, b"{}")).generate("m", None, "p", None, LlmLimits(retries=0))
            self.assertEqual(e.exception.kind, kind)

    def test_timeout_is_not_retried(self):
        c = self.client(LlmError("timeout"))
        with self.assertRaises(LlmError) as e:
            c.generate("m", None, "p", None, LlmLimits())
        self.assertEqual((e.exception.kind, len(self.script.calls)), ("timeout", 1))

    def test_empty_blocked_and_bad_response(self):
        cases = [({"candidates": []}, "empty"), ({"promptFeedback": {"blockReason": "SAFETY"}}, "blocked"),
                 ({"candidates": [{"finishReason": "SAFETY", "content": {"parts": []}}]}, "blocked"),
                 ({"candidates": [{"content": {"parts": [{"text": "  "}]}}]}, "empty")]
        for data, kind in cases:
            with self.assertRaises(LlmError) as e:
                self.client((200, {}, data)).generate("m", None, "p", None, LlmLimits())
            self.assertEqual(e.exception.kind, kind)
        with self.assertRaises(LlmError) as e:
            self.client((200, {}, b"not json")).generate("m", None, "p", None, LlmLimits())
        self.assertEqual(e.exception.kind, "bad_response")

    def test_key_required_and_settings_defaults(self):
        with self.assertRaises(ValueError):
            GeminiClient("")
        s = Settings.from_env({"SHEET_FORGE_LLM_API_KEY": " k ", "SHEET_FORGE_REREAD_MODEL": "gemini-y"})
        self.assertEqual((s.llm_api_key, s.reread_model), ("k", "gemini-y"))
        d = Settings.from_env({})
        self.assertEqual((d.llm_api_key, d.segment_model, d.read_model, d.reread_model, d.llm_timeout_s),
                         ("", "gemini-3.5-flash-lite", "gemini-3.5-flash-lite", "gemini-3.8-flash", 30))


if __name__ == "__main__":
    unittest.main()
