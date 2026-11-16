"""Gemini 공급자 어댑터(작업자 전용). 표준 라이브러리만 쓴다(HTTP는 transport로 바꿀 수 있어 테스트에서 가짜를 넣는다).

- 키는 헤더(x-goog-api-key)로만 보낸다. URL·로그·예외 메시지에 넣지 않는다.
- 429·5xx는 limits.retries번까지 지연 재시도하고(Retry-After가 있으면 따름, 최대 30초), 그 밖의 오류는 바로 LlmError.
- 출력 JSON은 해석하지 않고 text로 돌려준다(스키마 검증·수리는 B5-2b·3 몫).
"""
import base64
import json
import socket
import time
import urllib.error
import urllib.request

from ..ports import LlmError, LlmLimits, LlmResult

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_RETRY_STATUS = {429, 500, 502, 503, 504}
_MAX_DELAY_S = 30.0


def _urllib_transport(url, headers, body, timeout):
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read()
    except (socket.timeout, TimeoutError):
        raise LlmError("timeout") from None
    except urllib.error.URLError as e:
        raise LlmError("timeout" if isinstance(e.reason, (socket.timeout, TimeoutError)) else "network") from None


def _mime(image: bytes) -> str:
    return "image/png" if image[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"


class GeminiClient:
    def __init__(self, api_key: str, transport=None, sleep=time.sleep, base_url: str = BASE_URL):
        if not api_key:
            raise ValueError("api_key is required")
        self._key, self._transport, self._sleep, self._url = api_key, transport or _urllib_transport, sleep, base_url

    def _request(self, image, prompt, schema, limits: LlmLimits) -> bytes:
        parts = [{"text": prompt}]
        if image:
            parts.append({"inline_data": {"mime_type": _mime(image), "data": base64.b64encode(image).decode("ascii")}})
        cfg = {"temperature": limits.temperature, "maxOutputTokens": limits.max_output_tokens,
               "responseMimeType": "application/json"}
        if schema is not None:
            cfg["responseSchema"] = schema
        cfg.update(limits.generation_extra)
        return json.dumps({"contents": [{"role": "user", "parts": parts}], "generationConfig": cfg},
                          ensure_ascii=False).encode("utf-8")

    def generate(self, model, image, prompt, schema, limits: LlmLimits) -> LlmResult:
        url = self._url.format(model=model)
        headers = {"Content-Type": "application/json", "x-goog-api-key": self._key}
        body = self._request(image, prompt, schema, limits)
        t0 = time.monotonic()
        attempt = 0
        while True:
            status, resp_headers, raw = self._transport(url, headers, body, limits.timeout_s)
            if status == 200:
                break
            if status in _RETRY_STATUS and attempt < limits.retries:
                attempt += 1
                self._sleep(self._delay(resp_headers, attempt))
                continue
            raise LlmError(self._kind(status), status)
        return self._parse(raw, model, int((time.monotonic() - t0) * 1000))

    @staticmethod
    def _kind(status):
        if status == 429:
            return "rate_limit"
        if status >= 500:
            return "server"
        if status in (401, 403):
            return "auth"
        return "bad_request"

    @staticmethod
    def _delay(headers, attempt):
        for k, v in (headers or {}).items():
            if k.lower() == "retry-after":
                try:
                    return min(max(float(v), 0.0), _MAX_DELAY_S)
                except ValueError:
                    break
        return min(2.0 * attempt, _MAX_DELAY_S)

    @staticmethod
    def _parse(raw: bytes, model: str, latency_ms: int) -> LlmResult:
        try:
            data = json.loads(raw)
            usage = data.get("usageMetadata") or {}
            cands = data.get("candidates") or []
        except (ValueError, AttributeError):
            raise LlmError("bad_response") from None
        if not cands:
            raise LlmError("blocked" if (data.get("promptFeedback") or {}).get("blockReason") else "empty")
        cand = cands[0]
        finish = cand.get("finishReason")
        text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts") or [] if not p.get("thought"))
        if not text.strip():
            raise LlmError("blocked" if finish in ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "RECITATION") else "empty")
        return LlmResult(text=text, model=model, input_tokens=int(usage.get("promptTokenCount") or 0),
                         output_tokens=int(usage.get("candidatesTokenCount") or 0),
                         thinking_tokens=int(usage.get("thoughtsTokenCount") or 0),
                         latency_ms=latency_ms, finish_reason=finish)
