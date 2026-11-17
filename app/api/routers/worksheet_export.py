"""문제지 내보내기 엔드포인트 (REST 설계 5.7). 응답 모양은 `/exports`와 같다."""
import base64
import json
import logging
import time
from collections import Counter
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from ..deps import current_user, get_now, get_ro_session, get_session, get_settings, get_store
from ..schemas_misc import ERR_EXPORT, HWPX_200, ExportOut
from ..settings import Settings
from ..worksheet_export import record_last_export, run_worksheet_export, web_report

router = APIRouter()
log = logging.getLogger("sheet_forge.api")
HWPX_MEDIA = "application/vnd.hancom.hwpx"


@router.post("/worksheets/{worksheet_id}/export", response_model=ExportOut,
             responses={**HWPX_200, **ERR_EXPORT})
def export_worksheet(worksheet_id: str, request: Request, format: str = Query("json", pattern="^(json|hwpx)$"),
                     owner: str = Depends(current_user), ro_session: Session = Depends(get_ro_session),
                     session: Session = Depends(get_session), store=Depends(get_store),
                     settings: Settings = Depends(get_settings), now=Depends(get_now)):
    t0 = time.perf_counter()
    name, result, links = run_worksheet_export(ro_session, store, owner, worksheet_id, settings, now)
    report = result.report
    record_last_export(session, owner, worksheet_id, name, report.status, now)
    # 로그에는 개수·시간만 남긴다. 문항 내용·제목·이미지는 남기지 않는다 [설계 7장].
    log.info(json.dumps({"event": "worksheet_export", "request_id": getattr(request.state, "request_id", None),
                         "duration_ms": round((time.perf_counter() - t0) * 1000),
                         "stats": report.stats, "report_codes": dict(Counter(report.codes()))}, ensure_ascii=False))
    if format == "hwpx":
        n = lambda sev: sum(1 for i in report.items if i.severity == sev)
        return Response(result.hwpx_bytes, media_type=HWPX_MEDIA, headers={
            "Content-Disposition": f"attachment; filename=\"export.hwpx\"; filename*=UTF-8''{quote(name)}",
            "X-Export-Status": report.status, "X-Export-Warnings": str(n("warn")), "X-Export-Errors": str(n("error"))})
    return {"report": web_report(report.to_dict(), links),
            "file": {"name": name, "size": len(result.hwpx_bytes),
                     "content_base64": base64.b64encode(result.hwpx_bytes).decode("ascii")}}
