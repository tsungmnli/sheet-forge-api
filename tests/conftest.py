"""pytest 시작 때 저장소 루트 .env에서 테스트 DB 주소 하나만 읽는다(다른 값은 테스트 환경에 들이지 않는다).
이미 설정된 환경 변수가 우선한다."""
import os
from pathlib import Path

from dotenv import dotenv_values

_KEY = "SHEET_FORGE_TEST_DATABASE_URL"
if not os.environ.get(_KEY):
    _v = dotenv_values(Path(__file__).resolve().parent.parent / ".env").get(_KEY)
    if _v:
        os.environ[_KEY] = _v