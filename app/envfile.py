"""저장소 루트의 .env를 읽는다. 이미 설정된 환경 변수가 우선한다(클러스터의 Secret·ConfigMap이 이긴다)."""
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def load_env_file(path=None) -> bool:
    """파일이 있으면 읽고 True, 없으면 False(오류 아님)."""
    return load_dotenv(path or ROOT / ".env", override=False)
