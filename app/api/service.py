"""내보내기 서비스 (설계 2장): 제한 검사 → 입력 조립 → 라이브러리 호출."""
import re

from ..export.hwpx import ExportMeta, ExportRequest, export_hwpx
from .adapters.inline import InlineImages
from .errors import ApiError
from .schemas import ExportRequestBody
from .settings import Settings

_FORBIDDEN = re.compile(r'[/\\:*?"<>|\x00-\x1f\x7f]')


def safe_filename(title: str) -> str:
    """파일 시스템에 쓸 수 없는 문자를 없애고 120자로 자른다. 비면 '시험지'."""
    s = _FORBIDDEN.sub("", title or "")
    s = re.sub(r"\s+", "_", s.strip()).strip("._")[:120].strip("._")
    return (s or "시험지") + ".hwpx"


def run_export(body: ExportRequestBody, settings: Settings, now):
    if len(body.problems) > settings.max_problems:
        raise ApiError(413, "TOO_MANY_PROBLEMS", f"문항은 최대 {settings.max_problems}개")
    n_fig = sum(len(p.content.figures) for p in body.problems)
    if n_fig > settings.max_figures:
        raise ApiError(413, "TOO_MANY_FIGURES", f"그림은 최대 {settings.max_figures}개")
    images = InlineImages(body.images, settings.max_image_bytes, settings.max_image_px)
    problems = [p.model_dump(exclude_none=True) for p in body.problems]
    return export_hwpx(ExportRequest(problems, body.preset, ExportMeta(body.title, now), images))
