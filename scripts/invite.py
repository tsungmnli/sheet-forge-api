"""초대 메일을 보낸다. 받은 사람이 링크에서 비밀번호를 정하면 가입이 끝난다.

  uv run python scripts/invite.py 선생님@example.com

저장소 루트의 .env(또는 환경 변수)에서 DB 주소와 메일(SMTP) 설정을 읽는다. 운영 DB에 초대를 만들려면 그 DB 주소와
SMTP 설정이 들어 있어야 한다. SMTP_HOST가 없으면 메일은 보내지 않고 링크만 화면에 출력한다(개발용).
"""
import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api import auth_service  # noqa: E402
from app.api.errors import ApiError  # noqa: E402
from app.api.schemas_auth import normalize_email  # noqa: E402
from app.api.settings import Settings  # noqa: E402
from app.auth.mail import Mailer  # noqa: E402
from app.db.database import Database  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="초대 메일 보내기")
    ap.add_argument("email", help="초대할 이메일 주소")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")   # SMTP가 없을 때 mail.py가 링크를 로그로 남긴다
    settings = Settings.from_env()
    if not settings.database_url:
        print("SHEET_FORGE_DATABASE_URL이 없어요. .env를 확인해 주세요.")
        return 1
    if settings.smtp_host and not settings.web_base_url:
        print("SHEET_FORGE_WEB_BASE_URL이 없어요. 없으면 메일 링크가 깨져요.")
        return 1
    try:
        email = normalize_email(args.email)
    except ValueError as exc:
        print(exc)
        return 1
    db = Database(settings.database_url, "", 1, settings.db_connect_timeout_s)
    try:
        with db.session() as session:
            auth_service.send_invite(session, Mailer(settings), settings, email, now=datetime.now(timezone.utc))
    except ApiError as exc:
        print(exc.message)
        return 1
    finally:
        db.dispose()
    print(f"초대 메일을 보냈어요: {email}" if settings.smtp_host
          else "SMTP_HOST가 없어 메일은 보내지 않았어요. 위 링크를 직접 전달해 주세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
