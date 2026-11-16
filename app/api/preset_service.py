"""저장된 모양 (웹 REST API 설계 5.8): 내장 모양 + 내 모양 CRUD.

내장 모양은 코드 상수라 DB에 없고 고치거나 지울 수 없다. 문제지는 선택한 시점의 값을 복사해 가지므로
모양을 고치거나 지워도 이미 만든 문제지는 바뀌지 않는다.
"""
from sqlalchemy import select

from ..db.ids import new_id
from ..db.models import ExportPresetRecord
from ..export.hwpx import ExportPreset, plan_layout
from .errors import ApiError
from .repo import alive, soft_delete, update_versioned

BUILTIN_PREFIX = "builtin_"
_BUILTIN_DEFS = [
    ("builtin_a4_1col", "A4 한 칸", {}),
    ("builtin_b5_2col", "B5 두 칸", {"paper": {"kind": "B5", "width_mm": 182, "height_mm": 257},
                                     "columns": {"count": 2, "gap_mm": None}}),
]


def _builtin_value(overrides: dict) -> dict:
    d = ExportPreset().to_dict()
    for key, val in overrides.items():
        d[key] = {**d[key], **val}
    return ExportPreset.from_dict(d).to_dict()


def builtin_presets() -> list:
    return [{"id": pid, "name": name, "preset": _builtin_value(ov), "builtin": True, "version": None}
            for pid, name, ov in _BUILTIN_DEFS]


def _out(rec: ExportPresetRecord) -> dict:
    return {"id": rec.id, "name": rec.name, "preset": rec.preset, "builtin": False, "version": rec.version}


def _validated(raw: dict) -> dict:
    preset = ExportPreset.from_dict(raw)
    plan_layout(preset)              # 잘못된 모양이면 PresetError → 422 PRESET_INVALID
    return preset.to_dict()


def _reject_builtin(pid: str) -> None:
    if pid.startswith(BUILTIN_PREFIX):
        raise ApiError(409, "PRESET_BUILTIN")


def _load(session, owner: str, pid: str) -> ExportPresetRecord:
    rec = session.execute(select(ExportPresetRecord).where(ExportPresetRecord.id == pid,
                                                           *alive(ExportPresetRecord, owner))).scalar_one_or_none()
    if rec is None:
        raise ApiError(404, "NOT_FOUND")
    return rec


def get_preset_value(session, owner: str, pid: str) -> dict:
    """문제지가 복사해 갈 값. 내장 모양이거나 내 모양."""
    for b in builtin_presets():
        if b["id"] == pid:
            return b["preset"]
    return _load(session, owner, pid).preset


def list_presets(session, owner: str) -> dict:
    rows = session.scalars(select(ExportPresetRecord).where(*alive(ExportPresetRecord, owner))
                           .order_by(ExportPresetRecord.updated_at.desc(), ExportPresetRecord.id.desc()).limit(200))
    return {"items": builtin_presets() + [_out(r) for r in rows]}


def create_preset(session, owner: str, name: str, raw: dict) -> dict:
    rec = ExportPresetRecord(id=new_id("preset"), owner_id=owner, name=name, preset=_validated(raw))
    session.add(rec)
    session.commit()
    return _out(_load(session, owner, rec.id))


def update_preset(session, owner: str, pid: str, version: int, name: str, raw: dict) -> dict:
    _reject_builtin(pid)
    update_versioned(session, ExportPresetRecord, pid, owner, version, {"name": name, "preset": _validated(raw)})
    session.commit()
    return _out(_load(session, owner, pid))


def delete_preset(session, owner: str, pid: str) -> None:
    _reject_builtin(pid)
    soft_delete(session, ExportPresetRecord, pid, owner)
    session.commit()
