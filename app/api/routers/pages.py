"""사진 작업실 (웹 REST API 설계 5.3). 칸 고르기·고치기·보정 수정은 B2 이후."""
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from .. import segment_service, web_service as svc
from ..concurrency import etag_json
from ..deps import current_user, get_session
from ..schemas_web import PageDetailOut, SegmentPatchIn, SegmentsPutIn

router = APIRouter(prefix="/v1")


@router.get("/pages/{page_id}", response_model=PageDetailOut)
def get_page(page_id: str, request: Request, owner: str = Depends(current_user),
             session: Session = Depends(get_session)):
    payload = PageDetailOut.model_validate(svc.get_page_detail(session, owner, page_id)).model_dump(mode="json")
    return etag_json(request, payload)


@router.delete("/pages/{page_id}", status_code=204, response_class=Response)
def delete_page(page_id: str, owner: str = Depends(current_user), session: Session = Depends(get_session)):
    svc.delete_page(session, owner, page_id)
    return Response(status_code=204)


@router.patch("/pages/{page_id}/segments/{segment_id}")
def patch_segment(page_id: str, segment_id: str, body: SegmentPatchIn, owner: str = Depends(current_user),
                  session: Session = Depends(get_session)):
    """문제 고르기/해제. 읽은 문제가 있는 칸을 해제하면 409 SEGMENT_HAS_PROBLEM."""
    return segment_service.set_marked(session, owner, page_id, segment_id, body.marked)


@router.put("/pages/{page_id}/segments")
def put_segments(page_id: str, body: SegmentsPutIn, owner: str = Depends(current_user),
                 session: Session = Depends(get_session)):
    """"네모가 잘못됐어요" 저장: 칸 전체 목록으로 교체(id 있는 칸은 유지)."""
    return segment_service.replace_segments(session, owner, page_id, body.segments)
