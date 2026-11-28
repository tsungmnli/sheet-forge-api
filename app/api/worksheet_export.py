"""문제지 내보내기 (REST 설계 5.7): 문제지의 문제를 읽어 export_hwpx를 호출하고, 성공하면 last_export만 기록한다.

읽기(문제·그림)는 읽기 전용 세션으로, last_export 기록은 쓰기 세션으로 따로 한다(설계 D1).
파일은 보관하지 않는다. 문제지의 확인 안 된 문제 처리(unconfirmed_policy)는 모양의 on_unconfirmed에 덮어써 넘긴다.
"""
from sqlalchemy import update

from ..db.models import Worksheet
from ..export.hwpx import ExportMeta, ExportPreset, ExportRequest, export_hwpx
from .adapters.store_images import StoreImages
from .errors import ApiError
from .export_source import load_problems, load_worksheet
from .messages import report_message, report_summary
from .serialize import iso
from .service import safe_filename
from .settings import Settings


def run_worksheet_export(ro_session, store, owner: str, wid: str, settings: Settings, now):
    """(파일 이름, ExportResult, {problem_id: exam_id}). 라이브러리 예외(EmptyExportError 등)는 그대로 올린다."""
    ws = load_worksheet(ro_session, owner, wid)
    problems = load_problems(ro_session, ws)
    if len(problems) > settings.max_problems:
        raise ApiError(413, "TOO_MANY_PROBLEMS", f"문항은 최대 {settings.max_problems}개")
    if sum(len((p["content"] or {}).get("figures") or []) for p in problems) > settings.max_figures:
        raise ApiError(413, "TOO_MANY_FIGURES", f"그림은 최대 {settings.max_figures}개")
    preset = ExportPreset.from_dict(ws.preset)       # 잘못된 값이면 PresetError → 422
    preset.on_unconfirmed = ws.unconfirmed_policy    # 문제지 설정이 우선
    images = StoreImages(store, settings.max_image_bytes, settings.max_image_px)
    result = export_hwpx(ExportRequest(problems, preset, ExportMeta(ws.title, now, ws.subtitle), images))
    links = {p["id"]: p["exam_id"] for p in problems}   # 리포트 link용
    return safe_filename(ws.title), result, links


def add_links(report: dict, links: dict) -> dict:
    """리포트 항목 중 problem_id가 있는 것에 link{exam_id, problem_id}를 붙인다(웹의 문제 확인 화면 이동용)."""
    for item in report["items"]:
        pid = item.get("problem_id")
        if pid in links:
            item["link"] = {"exam_id": links[pid], "problem_id": pid}
    return report


def web_report(report: dict, links: dict) -> dict:
    """웹으로 나가는 리포트: link를 붙이고, 개발자용 message를 쉬운 문장으로 바꾸고, summary를 넣는다(설계 3.1·5.7)."""
    add_links(report, links)
    for item in report["items"]:
        item["message"] = report_message(item["code"], item.get("message"))
    report["summary"] = report_summary(report["items"])
    return report


def record_last_export(session, owner: str, wid: str, name: str, status: str, now) -> None:
    """last_export만 바꾼다. version·updated_at은 올리지 않는다(편집 중인 화면의 If-Match를 깨지 않도록)."""
    session.execute(update(Worksheet).where(Worksheet.id == wid, Worksheet.owner_id == owner)
                    .values(last_export={"at": iso(now), "name": name, "status": status}))
    session.commit()
