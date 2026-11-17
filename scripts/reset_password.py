"""비밀번호를 직접 바꾼다(메일 재설정을 못 쓸 때). 그 계정은 모든 기기에서 로그아웃된다.

  uv run python scripts/reset_password.py 선생님@example.com

새 비밀번호는 화면에 보이지 않게 입력한다. 바꾼 뒤 본인에게 새 비밀번호를 안전하게 전달한다.
"""
import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.api.schemas_auth import normalize_email  # noqa: E402
from app.api.settings import Settings  # noqa: E402
from app.auth.passwords import MAX_LENGTH, MIN_LENGTH, hash_password  # noqa: E402
from app.auth.sessions import revoke_user_sessions  # noqa: E402
from app.db.database import Database  # noqa: E402
from app.db.models import User  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="비밀번호 직접 재설정")
    ap.add_argument("email")
    args = ap.parse_args()
    settings = Settings.from_env()
    if not settings.database_url:
        print("SHEET_FORGE_DATABASE_URL이 없어요. .env를 확인해 주세요.")
        return 1
    try:
        email = normalize_email(args.email)
    except ValueError as exc:
        print(exc)
        return 1
    password = getpass.getpass("새 비밀번호: ")
    if not MIN_LENGTH <= len(password) <= MAX_LENGTH:
        print(f"비밀번호는 {MIN_LENGTH}~{MAX_LENGTH}자여야 해요.")
        return 1
    if getpass.getpass("한 번 더: ") != password:
        print("두 비밀번호가 달라요.")
        return 1
    db = Database(settings.database_url, "", 1, settings.db_connect_timeout_s)
    try:
        with db.session() as session:
            user = session.scalar(select(User).where(User.email == email))
            if user is None:
                print("가입한 이메일이 아니에요.")
                return 1
            user.password_hash = hash_password(password)
            revoke_user_sessions(session, user.id)
            session.commit()
    finally:
        db.dispose()
    print(f"비밀번호를 바꿨어요: {email}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
