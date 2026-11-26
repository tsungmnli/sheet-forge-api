"""엔진은 포트 뒤에 둔다(웹 REST API 설계 D5). B1은 PageProcessor만, Recognizer·FigureCleaner는 B2 이후."""
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class SegmentDraft:
    bbox: tuple  # (x0, y0, x1, y1), 보정본 기준 0~1 비율
    number: str | None
    choices_bbox: tuple | None = None  # B5-2b: 분할이 알려 준 선택지·그림 영역(문제 칸 안쪽, 같은 비율 좌표). 저장은 아직 안 함
    figure_bbox: tuple | None = None


@dataclass(frozen=True)
class PageResult:
    width: int | None
    height: int | None
    segments: list = field(default_factory=list)     # list[SegmentDraft], 읽는 순서
    corrected: bytes | None = None                    # None이면 원본을 보정본으로 쓴다
    corrected_content_type: str | None = None
    message: str | None = None                        # B5-2c: 폴백 등 선생님께 보일 쉬운 문장(processing.message에 둔다)
    usage: "LlmResult | None" = None                 # B5-2c: 분할 LLM 사용량(B5-3c에서 usage_events에 기록)
    fallback_reason: str | None = None                # B5-2c: 로그·계측용 종류만
    applied: dict | None = None                       # 실제로 쓴 보정 {corners, found, skew}. None이면 기록하지 않는다


class PageProcessor(Protocol):
    def process(self, data: bytes, content_type: str, correction: dict | None = None) -> PageResult:
        """사진 한 장 → 보정본(선택), 크기, 문제 칸. correction은 선생님이 고른 보정 설정(None이면 자동). 실패하면 예외."""
        ...


@dataclass(frozen=True)
class ReadResult:
    content: dict                                    # stem / choices (README 6.3). figures는 B5에서 채운다
    meta: dict = field(default_factory=dict)          # engine, tier 등. 문제 내용·이미지는 로그에 남기지 않는다
    points: float | None = None                       # 사진에 인쇄된 배점. 못 읽었으면 None(기존 값을 건드리지 않는다)
    figures: list = field(default_factory=list)       # 모델이 찾은 그림 상자 [{box_2d: [ymin,xmin,ymax,xmax](0~1000), placement}]. content["figures"]와 별개


@dataclass(frozen=True)
class CleanResult:
    clean: bytes | None                              # 정리한 그림. None이면 정리 실패(원본 그림을 쓴다)
    content_type: str | None = None


class Recognizer(Protocol):
    def read(self, crop: bytes, tier: str = "default") -> ReadResult:
        """문제 크롭 한 장 → 문제 내용. tier: default(기본) | high(다시 읽기). 실패하면 예외."""
        ...


class FigureCleaner(Protocol):
    def clean(self, raw: bytes, level: int = 2, keep_color: bool = False, erase_hues=None) -> CleanResult:
        """그림 크롭 → 정리본(필기·그림자 제거). level은 정리 세기 1~4. keep_color면 색 필기를 지우지 않는다.
        erase_hues(색상 값 목록)를 주면 그 색만 지운다. 실패하면 예외."""
        ...

    def palette(self, raw: bytes) -> list:
        """그림의 주요 색 견본 [{hue, rgb, share}]. 지울 색을 고르는 데 쓴다. 실패하면 예외."""
        ...


# ---- B5-2a: LLM 공급자 어댑터 포트 (설계 8.1). SDK·HTTP는 어댑터 안에만 둔다 ----
@dataclass(frozen=True)
class LlmLimits:
    timeout_s: float = 30.0
    max_output_tokens: int = 2000
    temperature: float = 0.0
    retries: int = 2                                  # 429·5xx만 지연 재시도(설계 8.2). 그 밖의 오류는 바로 실패
    generation_extra: dict = field(default_factory=dict)  # 추론 설정(thinkingConfig 등)을 generationConfig에 그대로 더한다


@dataclass(frozen=True)
class LlmResult:
    text: str                                         # 모델 출력(JSON 문자열). 내용은 로그에 남기지 않는다
    model: str
    input_tokens: int = 0
    output_tokens: int = 0                            # 생각 토큰은 따로 센다
    thinking_tokens: int = 0
    latency_ms: int = 0
    finish_reason: str | None = None


class LlmError(Exception):
    """kind: timeout | network | rate_limit | server | bad_request | auth | blocked | empty | bad_response.
    메시지에는 종류와 상태 코드만 담는다(응답 본문·키·문제 내용 없음).
    detail: 공급자가 알려 준 차단 종류 이름(SAFETY·RECITATION 등 대문자 상수만). blocked일 때만 있다."""

    def __init__(self, kind: str, status: int | None = None, detail: str | None = None):
        msg = kind if status is None else f"{kind}({status})"
        super().__init__(msg if detail is None else f"{msg}:{detail}")
        self.kind, self.status, self.detail = kind, status, detail


class LlmClient(Protocol):
    def generate(self, model: str, image: bytes | None, prompt: str, schema: dict | None, limits: LlmLimits) -> LlmResult:
        """프롬프트(+이미지 한 장) → JSON 출력. 실패하면 LlmError."""
        ...
