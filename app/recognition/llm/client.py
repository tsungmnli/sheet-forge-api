"""Gemini 공급자 어댑터(작업자 전용). 표준 라이브러리만 쓴다(HTTP는 transport로 바꿀 수 있어 테스트에서 가짜를 넣는다).

- 키는 헤더(x-goog-api-key)로만 보낸다. URL·로그·예외 메시지에 넣지 않는다.
- 429·5xx는 limits.retries번까지 지연 재시도하고(Retry-After가 있으면 따름, 최대 30초), 그 밖의 오류는 바로 LlmError.
- 출력 JSON은 해석하지 않고 text로 돌려준다(스키마 검증·수리는 B5-2b·3 몫).
"""
import base64
import json
import re
import socket
import time
import urllib.error
import urllib.request

from dataclasses import replace

from ..ports import LlmError, LlmLimits, LlmResult

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_RETRY_STATUS = {429, 500, 502, 503, 504}
_MAX_DELAY_S = 30.0
# 안전 필터를 조정할 수 있는 기본 범주. 시험지 글자·수식을 옮기는 용도라 기본은 끈다(BLOCK_NONE).
# 이 설정으로도 풀리지 않는 차단(저작물 반복 RECITATION, 금지 콘텐츠 PROHIBITED_CONTENT 등)이 있다.
_SAFETY_CATEGORIES = ("HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH",
                      "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT")
_BLOCKED_FINISH = ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "RECITATION", "SPII", "IMAGE_SAFETY")
# 저작물 반복(RECITATION)으로 막히면, 같은 글자를 그대로 옮기는 결정적 출력(온도 0)이 걸린 경우가 많아 온도를 조금 올려 한 번만 다시 부른다.
RECITATION_RETRY_TEMPERATURE = 0.7
_DETAIL_RE = re.compile(r"[A-Z_]{1,40}")


def _detail(name) -> str:
    """공급자가 준 차단 종류 이름. 대문자 상수가 아니면 내용이 섞였을 수 있어 버린다."""
    return name if isinstance(name, str) and _DETAIL_RE.fullmatch(name) else "OTHER"


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
    def __init__(self, api_key: str, transport=None, sleep=time.sleep, base_url: str = BASE_URL,
                 safety_threshold: str | None = "BLOCK_NONE"):
        if not api_key:
            raise ValueError("api_key is required")
        self._key, self._transport, self._sleep, self._url = api_key, transport or _urllib_transport, sleep, base_url
        t = (safety_threshold or "").strip().upper()
        self._safety = None if t in ("", "DEFAULT") else t   # 비우면 공급자 기본값을 쓴다

    def _request(self, image, prompt, schema, limits: LlmLimits) -> bytes:
        parts = [{"text": prompt}]
        if image:
            parts.append({"inline_data": {"mime_type": _mime(image), "data": base64.b64encode(image).decode("ascii")}})
        cfg = {"temperature": limits.temperature, "maxOutputTokens": limits.max_output_tokens,
               "responseMimeType": "application/json"}
        if schema is not None:
            cfg["responseSchema"] = schema
        cfg.update(limits.generation_extra)
        req = {"contents": [{"role": "user", "parts": parts}], "generationConfig": cfg}
        if self._safety:
            req["safetySettings"] = [{"category": c, "threshold": self._safety} for c in _SAFETY_CATEGORIES]
        return json.dumps(req, ensure_ascii=False).encode("utf-8")

    def generate(self, model, image, prompt, schema, limits: LlmLimits) -> LlmResult:
        try:
            return self._generate(model, image, prompt, schema, limits)
        except LlmError as e:
            if e.detail != "RECITATION":
                raise
        warm = replace(limits, temperature=max(limits.temperature, RECITATION_RETRY_TEMPERATURE))
        return self._generate(model, image, prompt, schema, warm)   # 이것도 막히면 그대로 올린다

    def _generate(self, model, image, prompt, schema, limits: LlmLimits) -> LlmResult:
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
            reason = (data.get("promptFeedback") or {}).get("blockReason")
            raise LlmError("blocked", detail=_detail(reason)) if reason else LlmError("empty")
        cand = cands[0]
        finish = cand.get("finishReason")
        text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts") or [] if not p.get("thought"))
        if not text.strip():
            raise LlmError("blocked", detail=_detail(finish)) if finish in _BLOCKED_FINISH else LlmError("empty")
        return LlmResult(text=text, model=model, input_tokens=int(usage.get("promptTokenCount") or 0),
                         output_tokens=int(usage.get("candidatesTokenCount") or 0),
                         thinking_tokens=int(usage.get("thoughtsTokenCount") or 0),
                         latency_ms=latency_ms, finish_reason=finish)
