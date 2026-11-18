"""B5-2c: 설정 -> PageProcessor. RECOGNITION_ENGINE=fake(기본) | real."""
import logging

from .fake import FakePageProcessor
from .ports import LlmLimits

log = logging.getLogger("sheet_forge.worker")


def build_processor(settings, client=None):
    engine = (settings.recognition_engine or "fake").strip().lower()
    if engine == "fake":
        log.warning("가짜 PageProcessor로 실행 중입니다(SHEET_FORGE_RECOGNITION_ENGINE=real로 바꾸면 실제 보정·분할을 씁니다).")
        return FakePageProcessor()
    if engine != "real":
        raise SystemExit("SHEET_FORGE_RECOGNITION_ENGINE은 fake 또는 real이어야 해요.")
    if client is None:
        if not settings.llm_api_key:
            raise SystemExit("SHEET_FORGE_RECOGNITION_ENGINE=real이면 SHEET_FORGE_LLM_API_KEY가 필요해요.")
        from .llm.client import GeminiClient
        client = GeminiClient(settings.llm_api_key, safety_threshold=settings.llm_safety_threshold)
    from .processor import RealPageProcessor
    limits = LlmLimits(timeout_s=float(settings.llm_timeout_s), max_output_tokens=8192)
    return RealPageProcessor(client, settings.segment_model, long_side=settings.segment_image_long_side, limits=limits)


# ---- B5-3b-4b-1: Recognizer ----
READ_MAX_OUTPUT = 2000   # 설계 6.3: 실측 최대 1,220토큰


def thinking_extra(model: str) -> dict:
    """설계 6.3: 추론 최소. 3.8 계열은 budget=0, 그 밖(3.5 계열)은 level=minimal. 키 이름이 공급자와 안 맞으면 호출이 400(bad_request)이 된다."""
    if "3.8" in model:
        return {"thinkingConfig": {"thinkingBudget": 0}}
    return {"thinkingConfig": {"thinkingLevel": "minimal"}}


def build_recognizer(settings, client=None):
    engine = (settings.recognition_engine or "fake").strip().lower()
    if engine == "fake":
        from .fake import FakeRecognizer
        log.warning("가짜 Recognizer로 실행 중입니다(SHEET_FORGE_RECOGNITION_ENGINE=real로 바꾸면 실제 읽기를 씁니다).")
        return FakeRecognizer()
    if engine != "real":
        raise SystemExit("SHEET_FORGE_RECOGNITION_ENGINE은 fake 또는 real이어야 해요.")
    if client is None:
        if not settings.llm_api_key:
            raise SystemExit("SHEET_FORGE_RECOGNITION_ENGINE=real이면 SHEET_FORGE_LLM_API_KEY가 필요해요.")
        from .llm.client import GeminiClient
        client = GeminiClient(settings.llm_api_key, safety_threshold=settings.llm_safety_threshold)
    from .llm.recognizer import RealRecognizer

    def limits(model, timeout_s):
        return LlmLimits(timeout_s=float(timeout_s), max_output_tokens=READ_MAX_OUTPUT,
                         generation_extra=thinking_extra(model))

    return RealRecognizer(client, settings.read_model, settings.reread_model,
                          limits=limits(settings.read_model, settings.llm_timeout_s),
                          high_limits=limits(settings.reread_model, settings.reread_timeout_s))


# ---- B5-4c: FigureCleaner ----
def build_cleaner(settings):
    """그림 정리기. fake(기본)는 정리 없이 원본을 돌려주고, real은 OpenCV 정리기를 쓴다(LLM 키 불필요)."""
    engine = (settings.recognition_engine or "fake").strip().lower()
    if engine == "fake":
        from .fake import FakeFigureCleaner
        log.warning("가짜 FigureCleaner로 실행 중입니다(SHEET_FORGE_RECOGNITION_ENGINE=real로 바꾸면 실제 그림 정리를 씁니다).")
        return FakeFigureCleaner()
    if engine != "real":
        raise SystemExit("SHEET_FORGE_RECOGNITION_ENGINE은 fake 또는 real이어야 해요.")
    from .vision.figure_clean import FigureCleaner
    return FigureCleaner()
