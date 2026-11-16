"""B5-2b-4: 분할 오케스트레이터 (설계 5.1~5.3). PageProcessor.detect의 알맹이.
LLM 분할 -> (성공) 가장자리 맞춤 / (호출 실패·출력 이상·0칸) 열 분할 폴백 + 안내 문장.
fallback_reason은 로그·계측용 종류만 담는다(응답 내용·사진 내용 없음)."""
import io
from dataclasses import dataclass

import numpy as np
from PIL import Image

from .llm.segment import DEFAULT_LONG_SIDE, segment_page
from .ports import LlmError, LlmLimits, LlmResult
from .vision.segment_fallback import FALLBACK_MESSAGE, detect_columns
from .vision.segment_post import SegmentParseError
from .vision.segment_snap import snap_segments


@dataclass(frozen=True)
class SegmentOutcome:
    segments: list                       # list[SegmentDraft], 읽는 순서
    usage: LlmResult | None = None       # LLM을 불렀고 응답을 받았을 때만(usage_events 기록용)
    fallback_reason: str | None = None   # None | "llm_error:<kind>" | "bad_output" | "no_problems"
    message: str | None = None           # 폴백일 때 processing.message에 둘 쉬운 문장


def _gray(corrected: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(corrected)) as im:
        im.load()
        return np.asarray(im.convert("L"))


def detect_segments(client, model: str, corrected: bytes, *, long_side: int = DEFAULT_LONG_SIDE,
                    limits: LlmLimits | None = None) -> SegmentOutcome:
    gray = _gray(corrected)
    try:
        segments, usage = segment_page(client, model, corrected, long_side=long_side, limits=limits)
    except LlmError as e:
        return SegmentOutcome(detect_columns(gray), None, f"llm_error:{e.kind}", FALLBACK_MESSAGE)
    except SegmentParseError:
        return SegmentOutcome(detect_columns(gray), None, "bad_output", FALLBACK_MESSAGE)
    if not segments:
        return SegmentOutcome(detect_columns(gray), usage, "no_problems", FALLBACK_MESSAGE)
    return SegmentOutcome(snap_segments(gray, segments), usage)
