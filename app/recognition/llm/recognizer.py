"""B5-3b-4a: 실제 Recognizer (설계 6.1~6.5). 크롭 1장 -> 읽기 LLM 1회 -> content 계약 -> 수식 점검 -> (필요하면) 수리 1회.
- 출력 형태 이상(ReadParseError)은 같은 모델로 1회 더 부르고, 또 실패하면 그대로 올린다(설계 6.4의 1).
- 호출 실패(LlmError)는 그대로 올린다(작업자의 재시도·실패 처리). 본문·선택지가 모두 비면 ReadEmptyError.
- tier=high(다시 읽기)는 상위 모델과 더 큰 크롭(긴 변 1,400px)을 쓴다. 프롬프트·후처리는 같다.
- 수리가 실패하거나 끝내 안 고쳐져도 읽기는 성공으로 본다. 남은 수식의 위치는 meta.math_failed(위치만, latex 없음).
- meta에는 문제 내용·이미지를 넣지 않는다. 호출별 사용량은 meta.usage에 두며 usage_events 기록은 B5-3c가 맡는다.
- GENERATION 설정(thinking 등)은 limits로 받는다. 이 클래스는 정하지 않는다(B5-3b-4b)."""
from ...export.math.convert import convert
from ..ports import LlmError, LlmLimits, ReadResult
from . import math_repair
from .blocks import inlines_of, iter_inlines
from .check import check_math
from .content import count_clamped, to_content
from .read import PROMPT_VERSION as READ_PROMPT, READ_LONG_SIDE, ReadParseError, read_crop

HIGH_LONG_SIDE = 1400
# 다시 읽기(상위 모델)가 이런 일시적 오류로 실패하면 처음 읽기 모델로 한 번 더 읽는다.
# 설정 문제(auth·bad_request)나 안전 차단(blocked)은 모델을 바꿔도 소용없으니 그대로 올린다.
FALLBACK_KINDS = ("timeout", "network", "server", "rate_limit")


class ReadEmptyError(ValueError):
    """읽기 결과의 본문·선택지가 모두 비었다(설계 6.4의 5). 메시지에는 종류만 담는다."""


def _is_empty(obj: dict) -> bool:
    for _, cont, key in iter_inlines(obj):
        for i in inlines_of(cont, key):
            if (i["v"] if i["t"] == "text" else i["latex"]).strip():
                return False
    return True


def _usage(call: str, model: str, r) -> dict:
    return {"call": call, "model": model, "input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
            "thinking_tokens": r.thinking_tokens, "latency_ms": r.latency_ms}


def _pos(d: dict, *extra) -> dict:
    return {k: d[k] for k in ("area", "para", "p", "r", "c", "inline") + extra if k in d}


class RealRecognizer:
    def __init__(self, client, model: str, high_model: str | None = None, *, repair_model: str | None = None,
                 limits: LlmLimits | None = None, high_limits: LlmLimits | None = None,
                 long_side: int = READ_LONG_SIDE,
                 high_long_side: int = HIGH_LONG_SIDE, convert_fn=convert):
        self.client, self.model, self.high_model = client, model, high_model or model
        self.repair_model, self.limits = repair_model, limits
        self.high_limits = limits if high_limits is None else high_limits
        self.long_side, self.high_long_side, self.convert_fn = long_side, high_long_side, convert_fn

    def _repair_limits(self, lim):
        if lim is None:
            return None
        return LlmLimits(timeout_s=lim.timeout_s, max_output_tokens=math_repair.MAX_OUTPUT,
                         temperature=lim.temperature, retries=lim.retries, generation_extra=lim.generation_extra)

    def read(self, crop: bytes, tier: str = "default") -> ReadResult:
        high = tier == "high"
        try:
            return self._read(crop, high, tier)
        except LlmError as e:
            if not high or e.kind not in FALLBACK_KINDS or self.model == self.high_model:
                raise
            # 상위 모델이 시간 초과 등으로 못 읽었다: 처음 읽기 모델·설정으로 한 번 더. 이것도 실패하면 그대로 올린다.
            res = self._read(crop, False, "default")
            res.meta["fallback"] = {"from_model": self.high_model, "reason": e.kind}   # 어떤 모델 결과인지 남긴다(내용 없음)
            return res

    def _read(self, crop: bytes, high: bool, tier: str) -> ReadResult:
        model = self.high_model if high else self.model
        long_side = self.high_long_side if high else self.long_side
        limits = self.high_limits if high else self.limits
        retried = False
        for attempt in (0, 1):
            try:
                obj, res, fixed_pieces = read_crop(self.client, model, crop, long_side=long_side, limits=limits)
                break
            except ReadParseError:
                if attempt:
                    raise
                retried = True
        usage = [_usage("read", model, res)]
        figures = [dict(f) for f in obj.get("figures") or []]   # 수식 고치기 전에 챙겨 둔다
        if _is_empty(obj):
            raise ReadEmptyError("empty")
        meta = {"engine": "llm", "tier": tier, "model": model, "prompt": READ_PROMPT, "fixed_pieces": fixed_pieces,
                "retried": retried, "uncertain": obj["uncertain"], "unsupported_block": obj["unsupported_block"],
                "math_repaired": 0, "repair_error": None}
        chk = check_math(obj, self.convert_fn)
        if chk.failures:
            rmodel = self.repair_model or model
            out = math_repair.repair_math(self.client, rmodel, obj, chk.failures, limits=self._repair_limits(limits),
                                          convert_fn=self.convert_fn)
            obj, meta["math_repaired"], meta["repair_error"] = out.obj, out.fixed, out.error_kind
            meta["repair_prompt"] = math_repair.PROMPT_VERSION
            if out.usage is not None:
                usage.append(_usage("repair", rmodel, out.usage))
            chk = check_math(obj, self.convert_fn)
        meta["math_failed"] = [_pos(f, "error_pos") for f in chk.failures]
        meta["math_warnings"] = [_pos(w, "warnings") for w in chk.warnings]
        clamped = count_clamped(obj)
        if clamped:
            meta["clamped_blocks"] = clamped   # 한계를 넘어 잘린 상자·표 수(없으면 키 없음)
        meta["usage"] = usage
        return ReadResult(content=to_content(obj), meta=meta, points=obj.get("points"), figures=figures)
