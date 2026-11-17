"""내 정보와 설정 (REST 설계 5.9). 설정은 바꾼 값만 저장하고 읽을 때 기본값과 합친다."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ..db.models import UserSettings
from .errors import ApiError
from .preset_service import get_preset_value

DEFAULTS = {
    "font_scale": 100,                       # 글자 크기 배율(%)
    "student_name_display": "full",          # full / alias / masked (가리는 건 웹이 한다)
    "original_photo_retention_days": 30,     # 7·30·90, 0 = 계속 보관
    "default_preset_id": None,               # 저장된 모양 id (내장 포함), 없으면 None
    "auto_next_after_confirm": True,         # 확인 완료 뒤 다음 문제로 자동 이동
}


class SettingsPatch(BaseModel):
    """바꿀 값만 보낸다. 모르는 키는 거절한다. default_preset_id만 null(해제)을 받는다."""
    model_config = ConfigDict(extra="forbid")
    font_scale: Literal[100, 115, 130, 150] | None = None
    student_name_display: Literal["full", "alias", "masked"] | None = None
    original_photo_retention_days: Literal[0, 7, 30, 90] | None = None
    default_preset_id: str | None = Field(None, max_length=40)
    auto_next_after_confirm: bool | None = None


def me(owner: str, email: str | None = None) -> dict:
    out = {"id": owner, "display_name": "선생님"}   # 표시 이름은 아직 고정 값
    if email is not None:
        out["email"] = email
    return out


def get_settings(session, owner: str) -> dict:
    row = session.get(UserSettings, owner)
    return {**DEFAULTS, **(row.data if row else {})}


def patch_settings(session, owner: str, body: SettingsPatch) -> dict:
    changes = {k: getattr(body, k) for k in body.model_fields_set}
    if any(v is None for k, v in changes.items() if k != "default_preset_id"):
        raise ApiError(422, "REQUEST_INVALID", "비울 수 없는 설정이에요.")
    pid = changes.get("default_preset_id")
    if pid is not None:
        try:
            get_preset_value(session, owner, pid)
        except ApiError:
            raise ApiError(422, "REQUEST_INVALID", "고른 모양을 찾을 수 없어요.") from None
    if changes:
        stmt = pg_insert(UserSettings).values(owner_id=owner, data=changes)
        session.execute(stmt.on_conflict_do_update(
            index_elements=["owner_id"],
            set_={"data": UserSettings.data.op("||")(stmt.excluded.data), "updated_at": func.now()}))
        session.commit()
    return get_settings(session, owner)
