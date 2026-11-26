"""사진 작업실 (웹 REST API 설계 5.3). 칸 고르기·고치기·사진 다시 보정하기."""
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from .. import correction_service, segment_service, web_service as svc
from ..concurrency import etag_json
from ..deps import current_user, get_session
from ..schemas_misc import ERR_RECORRECT, ERR_SEGMENT, ERR_SEGMENTS_PUT, SegmentPatchOut, SegmentsPutOut
from ..schemas_web import PageDetailOut, RecorrectIn, SegmentPatchIn, SegmentsPutIn

router = APIRouter()


@router.get("/pages/{page_id}", response_model=PageDetailOut)
def get_page(page_id: str, request: Request, owner: str = Depends(current_user),
             session: Session = Depends(get_session)):
    payload = PageDetailOut.model_validate(svc.get_page_detail(session, owner, page_id)).model_dump(mode="json")
    return etag_json(request, payload)


@router.delete("/pages/{page_id}", status_code=204, response_class=Response)
def delete_page(page_id: str, owner: str = Depends(current_user), session: Session = Depends(get_session)):
    svc.delete_page(session, owner, page_id)
    return Response(status_code=204)


@router.patch("/pages/{page_id}/segments/{segment_id}", response_model=SegmentPatchOut, responses=ERR_SEGMENT)
def patch_segment(page_id: str, segment_id: str, body: SegmentPatchIn, owner: str = Depends(current_user),
                  session: Session = Depends(get_session)):
    """문제 고르기/해제. 읽은 문제가 있는 칸을 해제하면 409 SEGMENT_HAS_PROBLEM."""
    return segment_service.set_marked(session, owner, page_id, segment_id, body.marked)


@router.put("/pages/{page_id}/segments", response_model=SegmentsPutOut, responses=ERR_SEGMENTS_PUT)
def put_segments(page_id: str, body: SegmentsPutIn, owner: str = Depends(current_user),
                 session: Session = Depends(get_session)):
    """"네모가 잘못됐어요" 저장: 칸 전체 목록으로 교체(id 있는 칸은 유지)."""
    return segment_service.replace_segments(session, owner, page_id, body.segments)


@router.post("/pages/{page_id}/recorrect", status_code=202, response_model=PageDetailOut, responses=ERR_RECORRECT)
def recorrect(page_id: str, body: RecorrectIn, owner: str = Depends(current_user),
              session: Session = Depends(get_session)):
    """사진 다시 보정하기: 설정 저장 → 칸 비우기 → 다시 처리. 끝날 때까지 processing을 폴링한다."""
    return correction_service.recorrect(session, owner, page_id, body.mode, body.rotation, body.corners, body.angle)
