"""B5-2c: 실제 PageProcessor. 사진 한 장 -> 보정본(JPEG) + 크기 + 문제 칸.
보정은 B5-1b의 correct_page(자동 꼭짓점), 분할은 B5-2b-4의 detect_segments. 분할이 실패해도 예외를 내지 않고
열 분할 폴백으로 칸을 만들며 message·fallback_reason에 알린다. 사진을 못 여는 등 보정 단계 실패는 예외로 올라가
작업자의 재시도·실패 처리를 탄다. 로그·예외 메시지에 사진·응답 내용은 넣지 않는다."""
from .llm.segment import DEFAULT_LONG_SIDE
from .ports import LlmLimits, PageResult
from .segmenter import detect_segments
from .vision.correct import applied_info, apply_correction
from .vision.decode import decode_image, encode_jpeg


class RealPageProcessor:
    def __init__(self, client, model: str, *, long_side: int = DEFAULT_LONG_SIDE, limits: LlmLimits | None = None):
        self.client, self.model, self.long_side, self.limits = client, model, long_side, limits

    def process(self, data: bytes, content_type: str, correction: dict | None = None) -> PageResult:
        c = apply_correction(decode_image(data), correction)
        image = c.image
        jpeg = encode_jpeg(image)
        out = detect_segments(self.client, self.model, jpeg, long_side=self.long_side, limits=self.limits)
        w, h = image.size
        return PageResult(width=w, height=h, segments=out.segments, corrected=jpeg,
                          corrected_content_type="image/jpeg", message=out.message, usage=out.usage,
                          fallback_reason=out.fallback_reason, applied=applied_info(c))
