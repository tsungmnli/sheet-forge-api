"""홈과 학생 (REST 설계 5.1)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import home_service as svc
from ..deps import current_user, get_session
from ..schemas_home import HomeOut, StudentsOut

router = APIRouter()


@router.get("/home", response_model=HomeOut)
def get_home(owner: str = Depends(current_user), session: Session = Depends(get_session)):
    """할 일: 확인 필요·읽는 중·읽기 실패 개수와 첫 번째 확인할 문제(없으면 null)."""
    return svc.home(session, owner)


@router.get("/students", response_model=StudentsOut)
def get_students(owner: str = Depends(current_user), session: Session = Depends(get_session)):
    """거르기용 학생 이름 목록."""
    return svc.students(session, owner)
