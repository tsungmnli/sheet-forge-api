# sheet-forge-api: hwpx 내보내기 API (설계 10장). 글꼴은 필요 없다(한글이 사용자 PC에서 해석).
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/srv/.venv/bin:$PATH"

WORKDIR /srv

# 의존성 레이어를 먼저(소스가 바뀌어도 캐시 재사용). CI가 테스트한 uv.lock 그대로 설치한다(운영 의존성만).
RUN pip install uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# 앱과 템플릿만 넣는다(tests·scripts는 .dockerignore로 제외)
COPY app ./app
COPY assets ./assets
COPY alembic.ini ./
COPY migrations ./migrations
# 운영에서 kubectl exec로 초대·비밀번호 재설정을 하려고 이 두 스크립트만 넣는다.
COPY scripts/invite.py scripts/reset_password.py ./scripts/

RUN useradd --system --uid 10001 --no-create-home app
USER 10001

EXPOSE 8000
# 워커 수는 WEB_CONCURRENCY 환경 변수로 바꾼다(uvicorn이 읽음). 무상태라 레플리카로도 늘릴 수 있다.
ENV WEB_CONCURRENCY=2
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-access-log"]
