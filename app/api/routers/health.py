from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/healthz")
def healthz():
    """liveness: 외부 의존성(DB 등)을 보지 않는다. DB가 죽어도 파드가 재시작되지 않게."""
    return {"status": "ok"}


@router.get("/readyz")
def readyz(request: Request):
    """readiness: 등록된 점검(템플릿 로드, 이후 DB 등)을 모두 통과해야 ok."""
    results = {}
    for name, check in request.app.state.readiness_checks.items():
        try:
            check()
            results[name] = True
        except Exception:  # noqa: BLE001 — 점검 실패는 상태로만 알린다
            results[name] = False
    ok = all(results.values())
    return JSONResponse({"status": "ok" if ok else "unavailable", "checks": results}, status_code=200 if ok else 503)
