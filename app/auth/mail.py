"""메일 발송(SMTP). 운영은 Resend: host smtp.resend.com, port 465, user resend, password = Resend API 키.

SMTP_HOST가 없으면(개발·테스트) 보내지 않고 로그에 남긴다. 링크를 로그에서 복사해 쓸 수 있다.
"""
import logging
import smtplib
import ssl
from email.message import EmailMessage

from ..api.settings import Settings

log = logging.getLogger("sheet_forge.mail")
TIMEOUT = 10  # 초


class MailError(RuntimeError):
    """메일 서버에 넘기지 못했다."""


class Mailer:
    """app.state.mailer로 둔다. 테스트에서는 보낸 메일을 기록하는 가짜로 바꾼다."""

    def __init__(self, settings: Settings) -> None:
        self._s = settings

    def send(self, to: str, subject: str, text: str) -> None:
        s = self._s
        if not s.smtp_host:
            log.info("메일 안 보냄(SMTP_HOST 없음)\nto: %s\nsubject: %s\n\n%s", to, subject, text)
            return
        msg = EmailMessage()
        msg["From"] = s.smtp_from
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(text)
        context = ssl.create_default_context()
        try:
            if s.smtp_port == 465:  # 암묵적 TLS
                with smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=TIMEOUT, context=context) as c:
                    self._deliver(c, msg)
            else:
                with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=TIMEOUT) as c:
                    c.starttls(context=context)
                    self._deliver(c, msg)
        except (smtplib.SMTPException, OSError) as exc:
            raise MailError(f"SMTP 발송 실패({s.smtp_host}): {type(exc).__name__}") from exc

    def _deliver(self, conn: smtplib.SMTP, msg: EmailMessage) -> None:
        if self._s.smtp_user and self._s.smtp_password:
            conn.login(self._s.smtp_user, self._s.smtp_password)
        conn.send_message(msg)
