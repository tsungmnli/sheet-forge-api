"""정기 정리 (REST 설계 6장 purge_trash·purge_originals). 로그에는 종류별 개수만 남긴다."""
import logging
from datetime import datetime, timedelta, timezone

from ..api.me_service import DEFAULTS
from ..purge import purge_originals, purge_trash_with_images

log = logging.getLogger("sheet_forge.worker")


def run_maintenance(db, store, trash_retention_days: int, now: datetime | None = None) -> dict:
    """보존 기간이 지난 휴지통 항목(행·이미지)과 원본 사진을 정리한다. 여러 번·동시에 실행해도 안전하다(조건에 맞는 행만 지운다)."""
    now = now or datetime.now(timezone.utc)
    with db.session() as s:
        trash = purge_trash_with_images(s, store, now - timedelta(days=trash_retention_days))
    with db.session() as s:
        originals = purge_originals(s, store, now, DEFAULTS["original_photo_retention_days"])
    log.info("정기 정리: 휴지통 %s, 이미지 %s, 원본 사진 %d장(이미지 %s)",
             trash["counts"], trash["images"], originals["pages"], originals["images"])
    return {"trash": trash, "originals": originals}
