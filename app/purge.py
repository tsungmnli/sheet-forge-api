"""휴지통 영구 삭제 (REST 설계 5.9, 6장 purge_trash). DB 행만 지우고, 지운 행이 쓰던 이미지 ref 후보를 돌려준다.
저장소 객체 삭제는 호출하는 쪽(B4-6b)이 한다.

같이 지워진 행은 같은 시각(deleted_at)을 갖고, 따로 지운 행은 자기 시각을 가진다. 그래서 행마다 deleted_at이 기준보다 오래됐는지만 보면 된다.
아직 만료되지 않은 행이 참조하는 부모(칸·사진·시험지)는 지우지 않는다(FK 보호). 다음 정리 때 지워진다.
"""
from datetime import datetime

from sqlalchemy import Integer, Text, cast, delete, exists, func, select, update

from .db.models import Exam, Page, Problem, Segment, UserSettings, Worksheet, WorksheetItem
from .storage.images import StorageError


def _figure_refs(content) -> list:
    out = []
    for f in (content or {}).get("figures") or []:
        out.extend(v for v in (f.get("raw_ref"), f.get("clean_ref"), f.get("pick_ref"), *(f.get("levels") or {}).values()) if v)
    return out


def purge_trash(session, cutoff: datetime) -> dict:
    """deleted_at이 cutoff 이하인 휴지통 행을 영구 삭제한다. {"counts": {종류: 개수}, "refs": [이미지 ref 후보]}를 돌려준다.

    문제지에 담겨 있던 문제는 문제지에서도 빠진다(담긴 목록 항목 삭제). 문제지 자체는 자기 deleted_at으로만 지운다.
    """
    old = lambda m: (m.deleted_at.is_not(None), m.deleted_at <= cutoff)  # noqa: E731
    counts, refs = {}, []

    # 1. 문제지 목록 항목: 만료된 문제 또는 만료된 문제지에 속한 것
    session.execute(delete(WorksheetItem).where(
        WorksheetItem.problem_id.in_(select(Problem.id).where(*old(Problem)))
        | WorksheetItem.worksheet_id.in_(select(Worksheet.id).where(*old(Worksheet)))))
    # 2. 문제 → 칸 → 사진 → 시험지 (아래쪽이 위쪽을 참조하므로 이 순서)
    rows = session.execute(delete(Problem).where(*old(Problem)).returning(Problem.crop_ref, Problem.content, Problem.ocr_meta)).all()
    counts["problem"] = len(rows)
    for crop_ref, content, meta in rows:
        refs.extend([crop_ref] if crop_ref else [])
        refs.extend(_figure_refs(content))
        refs.extend(_figure_refs({"figures": (meta or {}).get("removed_figures")}))  # 지웠지만 보관 중이던 그림
    counts["segment"] = session.execute(delete(Segment).where(
        *old(Segment), ~exists(select(Problem.id).where(Problem.segment_id == Segment.id)))).rowcount
    rows = session.execute(delete(Page).where(
        *old(Page), ~exists(select(Segment.id).where(Segment.page_id == Page.id))
    ).returning(Page.original_ref, Page.corrected_ref)).all()
    counts["page"] = len(rows)
    for original_ref, corrected_ref in rows:
        refs.extend(r for r in (original_ref, corrected_ref) if r)
    counts["exam"] = session.execute(delete(Exam).where(
        *old(Exam),
        ~exists(select(Page.id).where(Page.exam_id == Exam.id)),
        ~exists(select(Segment.id).where(Segment.exam_id == Exam.id)),
        ~exists(select(Problem.id).where(Problem.exam_id == Exam.id)))).rowcount
    # 3. 문제지
    counts["worksheet"] = session.execute(delete(Worksheet).where(*old(Worksheet))).rowcount
    session.commit()
    return {"counts": counts, "refs": sorted(set(refs))}


# ---------- 이미지 객체 삭제 (B4-6b) ----------
def _referenced(session, ref: str) -> bool:
    """남아 있는 행(휴지통 포함)이 이 ref를 쓰고 있는가. 문제 내용(JSONB)은 문자열 포함 여부로 보수적으로 확인한다(잘못 남길 수는 있어도 잘못 지우지는 않는다)."""
    return bool(
        session.execute(select(Page.id).where((Page.original_ref == ref) | (Page.corrected_ref == ref)).limit(1)).first()
        or session.execute(select(Problem.id).where(
            (Problem.crop_ref == ref) | (func.strpos(cast(Problem.content, Text), ref) > 0)).limit(1)).first())


def delete_unreferenced_images(session, store, refs) -> dict:
    """refs 중 다른 행이 쓰지 않는 객체만 저장소에서 지운다. 저장소 오류는 그 ref만 건너뛴다(고아 객체로 남을 뿐 데이터는 안전).
    {"deleted": n, "kept": n(아직 쓰이는 것), "failed": n} (내용·ref는 돌려주지 않는다)."""
    deleted = kept = failed = 0
    for ref in refs:
        if _referenced(session, ref):
            kept += 1
            continue
        try:
            store.delete(ref)
            deleted += 1
        except StorageError:
            failed += 1
    return {"deleted": deleted, "kept": kept, "failed": failed}


def purge_trash_with_images(session, store, cutoff: datetime) -> dict:
    """행을 먼저 영구 삭제(커밋)하고, 그 뒤 이미지 객체를 지운다. 중간에 멈춰도 행이 없는 고아 객체가 남을 뿐이다."""
    res = purge_trash(session, cutoff)
    res["images"] = delete_unreferenced_images(session, store, res.pop("refs"))
    return res


# ---------- 원본 사진 보존 기간 (B4-6c) ----------
def purge_originals(session, store, now: datetime, default_days: int = 30) -> dict:
    """보존 기간(사용자 설정 original_photo_retention_days, 없으면 default_days, 0 = 계속 보관)이 지난 사진의 원본만 지운다.
    보정본·문제 크롭·그림은 남는다. 보정본이 없거나 원본과 같은 객체인 사진은 지울 수 없어 건너뛴다. 기준은 사진을 올린 시각.
    {"pages": n, "images": {deleted, kept, failed}}"""
    days = func.coalesce(cast(UserSettings.data["original_photo_retention_days"].astext, Integer), default_days)
    rows = session.execute(
        select(Page.id, Page.original_ref).outerjoin(UserSettings, UserSettings.owner_id == Page.owner_id)
        .where(Page.original_ref.is_not(None), Page.corrected_ref.is_not(None), Page.corrected_ref != Page.original_ref,
               days > 0, Page.created_at + func.make_interval(0, 0, 0, days) <= now)).all()
    if rows:
        session.execute(update(Page).where(Page.id.in_([r[0] for r in rows]), Page.original_ref.is_not(None))
                        .values(original_ref=None, version=Page.version + 1, updated_at=func.now()))
        session.commit()
    return {"pages": len(rows), "images": delete_unreferenced_images(session, store, [r[1] for r in rows])}
