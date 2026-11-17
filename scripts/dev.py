"""로컬 개발용: API 서버와 작업자를 한 번에 띄운다.

    uv run python scripts/dev.py

Ctrl+C로 둘 다 끈다. 하나가 먼저 죽으면 나머지도 끈다.
API는 --reload로 뜨고, 작업자는 코드를 고치면 다시 실행해야 한다.
"""
import subprocess
import sys
import time

COMMANDS = [
    [sys.executable, "-m", "uvicorn", "app.api.main:app", "--reload"],
    [sys.executable, "-m", "app.worker"],
]


def main() -> int:
    procs = [subprocess.Popen(cmd) for cmd in COMMANDS]
    try:
        while all(p.poll() is None for p in procs):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
