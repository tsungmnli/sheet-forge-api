"""B5-3c-1: LLM 사용량 기록(설계 8.1). 호출 한 번이 usage_events 한 줄이다.
이벤트는 {call, model, input_tokens, output_tokens, thinking_tokens, latency_ms} 모양의 dict이며,
RealRecognizer가 meta.usage에 담는 것과 같다. 문제 내용·이미지·프롬프트는 어디에도 담지 않는다.
record_usage는 세션에 행만 더하고 커밋하지 않는다(호출하는 쪽의 트랜잭션에 함께 묶는다)."""
import logging

from ..db.models import UsageEvent

_log = logging.getLogger("sheet_forge.worker")


def llm_event(call: str, model: str, result) -> dict:
    """LlmResult -> 이벤트. model이 비어 있으면 result.model을 쓴다."""
    return {"call": call, "model": model or result.model, "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens, "thinking_tokens": result.thinking_tokens,
            "latency_ms": result.latency_ms}


def record_usage(session, owner_id: str, job_kind: str, target_id: str, events) -> int:
    n = 0
    for e in events or []:
        session.add(UsageEvent(owner_id=owner_id, job_kind=job_kind, target_id=target_id, call=e["call"],
                               model=e["model"], input_tokens=int(e.get("input_tokens") or 0),
                               output_tokens=int(e.get("output_tokens") or 0),
                               thinking_tokens=int(e.get("thinking_tokens") or 0),
                               latency_ms=int(e.get("latency_ms") or 0)))
        n += 1
    return n


def record_job_usage(db, job, events) -> None:
    """작업 하나의 LLM 호출 사용량을 별도 트랜잭션으로 기록한다(호출 직후 부른다).
    기록이 실패해도 작업은 계속하고, 로그에는 작업 id·종류·예외 이름만 남긴다."""
    if not events:
        return
    try:
        with db.session() as s:
            record_usage(s, job.owner_id, job.kind, job.target_id, events)
            s.commit()
    except Exception as exc:  # noqa: BLE001 - 기록 실패가 읽기·분할 결과를 막지 않게
        _log.warning("사용량 기록 실패 job=%s kind=%s err=%s", job.id, job.kind, type(exc).__name__)
