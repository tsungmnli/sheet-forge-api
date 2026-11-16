import base64
import json
import logging
import time
from collections import Counter
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request, Response

from ...export.hwpx import ExportPreset, plan_layout
from ..deps import get_now, get_settings
from ..schemas import ExportRequestBody, LayoutPreviewBody
from ..service import run_export, safe_filename
from ..settings import Settings

router = APIRouter(prefix="/v1")
log = logging.getLogger("sheet_forge.api")
HWPX_MEDIA = "application/vnd.hancom.hwpx"

PAPERS = [{"kind": "A4", "width_mm": 210, "height_mm": 297}, {"kind": "B5", "width_mm": 182, "height_mm": 257}]


@router.post("/exports")
def create_export(body: ExportRequestBody, request: Request, format: str = Query("json", pattern="^(json|hwpx)$"),
                  settings: Settings = Depends(get_settings), now=Depends(get_now)):
    t0 = time.perf_counter()
    result = run_export(body, settings, now)
    report = result.report
    name = safe_filename(body.title)
    # 로그에는 개수·시간만 남긴다. 문항 내용·제목·이미지는 남기지 않는다 [설계 7장].
    log.info(json.dumps({"event": "export", "request_id": getattr(request.state, "request_id", None),
                         "title_len": len(body.title), "duration_ms": round((time.perf_counter() - t0) * 1000),
                         "stats": report.stats, "report_codes": dict(Counter(report.codes()))}, ensure_ascii=False))
    if format == "hwpx":
        n = lambda sev: sum(1 for i in report.items if i.severity == sev)
        return Response(result.hwpx_bytes, media_type=HWPX_MEDIA, headers={
            "Content-Disposition": f"attachment; filename=\"export.hwpx\"; filename*=UTF-8''{quote(name)}",
            "X-Export-Status": report.status, "X-Export-Warnings": str(n("warn")), "X-Export-Errors": str(n("error"))})
    return {"report": report.to_dict(),
            "file": {"name": name, "size": len(result.hwpx_bytes),
                     "content_base64": base64.b64encode(result.hwpx_bytes).decode("ascii")}}


@router.post("/exports/layout-preview")
def layout_preview(body: LayoutPreviewBody):
    preset = ExportPreset.from_dict(body.preset)
    layout = plan_layout(preset)  # 잘못된 preset은 PresetError → 422
    return {"layout": layout.summary(), "effective_preset": preset.to_dict()}


@router.get("/export-presets/defaults")
def preset_defaults():
    return {"preset": ExportPreset().to_dict(), "papers": PAPERS}
