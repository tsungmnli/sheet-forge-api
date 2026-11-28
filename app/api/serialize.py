"""DB 행 → 응답 dict (웹 REST API 설계 4·5장)."""
from datetime import timezone

POLL_MS = 2000
# 브라우저가 보는 바깥 접두어. Ingress가 떼므로 앱 경로에는 붙이지 않는다(FastAPI root_path와 이미지 URL이 같이 쓴다).
API_PREFIX = "/api"


def iso(dt) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def image_url(ref):
    return f"{API_PREFIX}/images/{ref}" if ref else None


def is_active(processing) -> bool:
    return (processing or {}).get("state") in ("queued", "running")


def next_action(page_count: int, picked_count: int, unread_count: int, needs_review: int, confirmed: int) -> str:
    """시험지 화면의 '다음에 할 일'. 서버가 계산해 화면과 내보내기가 같은 규칙을 쓴다."""
    if page_count == 0:
        return "upload"
    if picked_count == 0:
        return "pick"
    if unread_count > 0:
        return "read"
    if needs_review > 0:
        return "review"
    return "worksheet"


def exam_out(exam, page_count, picked, active) -> dict:
    page_count, picked = int(page_count), int(picked)
    return {"id": exam.id, "title": exam.title, "student": exam.student, "memo": exam.memo,
            "source_label": exam.source_label, "version": exam.version,
            "created_at": iso(exam.created_at), "updated_at": iso(exam.updated_at),
            "page_count": page_count, "picked_count": picked,
            "needs_review": 0, "confirmed": 0,  # 문제(Problem)는 B2에서 생긴다
            "next_action": next_action(page_count, picked, picked, 0, 0),
            "poll_after_ms": POLL_MS if int(active) else None}


def processing_out(p) -> dict:
    p = p or {}
    return {"state": p.get("state", "queued"), "step": p.get("step"), "message": p.get("message")}


def page_out(page, picked) -> dict:
    return {"id": page.id, "exam_id": page.exam_id, "order": page.position,
            "thumb_url": image_url(page.corrected_ref or page.original_ref),
            "processing": processing_out(page.processing), "picked_count": int(picked), "version": page.version}


def page_detail(page, picked, segments) -> dict:
    d = page_out(page, picked)
    d.update({"image": {"original_url": image_url(page.original_ref), "corrected_url": image_url(page.corrected_ref),
                        "width": page.width, "height": page.height},
              "correction": page.correction,
              "segments": [{"id": s.id, "bbox": list(s.bbox), "number": s.number, "marked": s.marked} for s in segments],
              "poll_after_ms": POLL_MS if is_active(page.processing) else None})
    return d
