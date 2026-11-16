"""빈 템플릿 hwpx 로더 (설계 6장). 파트를 읽기 전용으로 보관하고 내보낼 때마다 복사본을 쓴다."""
import zipfile
from pathlib import Path

from .errors import TemplateError

DEFAULT_TEMPLATE = Path(__file__).resolve().parents[3] / "assets" / "templates" / "blank.hwpx"


class Template:
    def __init__(self, parts: dict):
        self._parts = dict(parts)  # name -> bytes, 템플릿 순서 유지
        for needed in ("mimetype", "Contents/header.xml", "Contents/section0.xml", "Contents/content.hpf"):
            if needed not in self._parts:
                raise TemplateError(f"템플릿에 {needed}가 없음")

    @classmethod
    def load(cls, path=None) -> "Template":
        path = Path(path) if path else DEFAULT_TEMPLATE
        try:
            with zipfile.ZipFile(path) as z:
                parts = {i.filename: z.read(i.filename) for i in z.infolist() if not i.is_dir()}
        except (OSError, zipfile.BadZipFile) as ex:
            raise TemplateError(f"템플릿을 읽을 수 없음: {path} ({ex})") from ex
        return cls(parts)

    def names(self) -> list:
        return list(self._parts)

    def text(self, name: str) -> str:
        return self._parts[name].decode("utf-8")

    def raw(self, name: str) -> bytes:
        return self._parts[name]

    def copy_parts(self) -> dict:
        return dict(self._parts)
