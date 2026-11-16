"""B5-2b-2: 분할 호출 (보정본 -> 축소 JPEG -> LLM 1회 -> 문제 칸). 설계 5.1.
공급자는 모르고 LlmClient 포트만 쓴다. 실패 처리(열 분할 폴백)는 호출하는 쪽(B5-2b-4)이 한다:
LlmError(호출 실패) 또는 SegmentParseError(출력 형태 이상)가 그대로 올라온다. 칸이 0개면 빈 목록."""
import io
from pathlib import Path

from PIL import Image

from ..ports import LlmLimits
from ..vision.segment_post import segments_from_llm
from .schemas import SEGMENT_SCHEMA

PROMPT_VERSION = "segment_v2"
PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / (PROMPT_VERSION + ".md")
DEFAULT_LONG_SIDE = 1500    # 설계 5.1 / 8.3 SEGMENT_IMAGE_LONG_SIDE
DEFAULT_MAX_OUTPUT = 8192   # 추론 토큰이 출력 한도를 나눠 쓰다 JSON이 잘리는 일을 막으려고 넉넉히 둔다


def load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")


def shrink_for_segment(data: bytes, long_side: int = DEFAULT_LONG_SIDE) -> bytes:
    """보정본을 긴 변 long_side px 이하의 JPEG로 줄인다(작으면 크기는 그대로, JPEG로만 바꾼다)."""
    with Image.open(io.BytesIO(data)) as im:
        im.load()
        im = im.convert("RGB")
        im.thumbnail((long_side, long_side), Image.LANCZOS)
        out = io.BytesIO()
        im.save(out, "JPEG", quality=85)
    return out.getvalue()


def segment_page(client, model: str, corrected: bytes, *, long_side: int = DEFAULT_LONG_SIDE,
                 limits: LlmLimits | None = None):
    """(읽는 순서의 SegmentDraft 목록, LlmResult)를 돌려준다. LlmResult는 usage_events 기록용(B5-3c)."""
    limits = limits or LlmLimits(max_output_tokens=DEFAULT_MAX_OUTPUT)
    result = client.generate(model, shrink_for_segment(corrected, long_side), load_prompt(), SEGMENT_SCHEMA, limits)
    return segments_from_llm(result.text), result
