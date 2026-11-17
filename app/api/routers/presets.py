"""저장된 모양 (웹 REST API 설계 5.8). 기본 모양·폭 미리보기는 routers/exports.py에 이미 있다."""
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from .. import preset_service as svc
from ..concurrency import etag, require_if_match
from ..deps import current_user, get_session
from ..preset_shape import PresetValue, PresetValueOut

router = APIRouter()


class PresetIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    preset: PresetValue


class PresetOut(BaseModel):
    id: str
    name: str
    preset: PresetValueOut
    builtin: bool
    version: int | None


class PresetListOut(BaseModel):
    items: list[PresetOut]


@router.get("/export-presets", response_model=PresetListOut)
def list_presets(owner: str = Depends(current_user), session: Session = Depends(get_session)):
    return svc.list_presets(session, owner)


@router.post("/export-presets", status_code=201, response_model=PresetOut)
def create_preset(body: PresetIn, response: Response, owner: str = Depends(current_user),
                  session: Session = Depends(get_session)):
    out = svc.create_preset(session, owner, body.name, body.preset)
    response.headers["ETag"] = etag(out["version"])
    return out


@router.put("/export-presets/{preset_id}", response_model=PresetOut)
def update_preset(preset_id: str, body: PresetIn, response: Response, version: int = Depends(require_if_match),
                  owner: str = Depends(current_user), session: Session = Depends(get_session)):
    out = svc.update_preset(session, owner, preset_id, version, body.name, body.preset)
    response.headers["ETag"] = etag(out["version"])
    return out


@router.delete("/export-presets/{preset_id}", status_code=204, response_class=Response)
def delete_preset(preset_id: str, owner: str = Depends(current_user), session: Session = Depends(get_session)):
    svc.delete_preset(session, owner, preset_id)
    return Response(status_code=204)
