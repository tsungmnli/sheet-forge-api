"""content.hpf 메타 덮어쓰기, Preview 제거, zip 패키징 (설계 12장) [검증 4.1, 4.8]."""
import io
import re
import zipfile
from xml.sax.saxutils import escape

FIXED_TIME = (1980, 1, 1, 0, 0, 0)
STORED = {"mimetype", "version.xml"}


def _set_meta(hpf: str, name: str, value: str) -> str:
    pat = re.compile(rf'<opf:meta name="{name}" content="text"(?:/>|>[^<]*</opf:meta>)')
    new = (f'<opf:meta name="{name}" content="text">{escape(value)}</opf:meta>' if value
           else f'<opf:meta name="{name}" content="text"/>')
    out, n = pat.subn(lambda _m: new, hpf, count=1)
    return out if n else hpf


def patch_hpf(hpf: str, title: str, created_iso: str, n_images: int = 0) -> str:
    """템플릿의 작성자·날짜는 항상 덮어쓴다(개인 식별 정보 제거). n_images개의 PNG를 manifest에 등록한다."""
    hpf = re.sub(r"<opf:title\s*/>|<opf:title>[^<]*</opf:title>",
                 lambda _m: f"<opf:title>{escape(title)}</opf:title>" if title else "<opf:title/>", hpf, count=1)
    for name in ("creator", "lastsaveby", "date", "subject", "description", "keyword"):
        hpf = _set_meta(hpf, name, "")
    for name in ("CreatedDate", "ModifiedDate"):
        hpf = _set_meta(hpf, name, created_iso)
    if n_images:
        items = "".join(f'<opf:item id="image{k}" href="BinData/image{k}.png" media-type="image/png" isEmbeded="1"/>'
                        for k in range(1, n_images + 1))
        hpf = hpf.replace("</opf:manifest>", items + "</opf:manifest>", 1)
    return hpf


def strip_preview(parts: dict) -> dict:
    """Preview/ 제거 + container.xml의 PrvText 줄 제거 [검증 4.1, t4]."""
    out = {k: v for k, v in parts.items() if not k.startswith("Preview/")}
    c = out.get("META-INF/container.xml")
    if c is not None:
        out["META-INF/container.xml"] = re.sub(
            rb'<ocf:rootfile full-path="Preview/[^"]*"[^>]*/>', b"", c)
    return out


def build_zip(parts: dict) -> bytes:
    """mimetype 첫 항목·무압축, version.xml 무압축, 나머지 deflate, 항목 시각 고정(결정적 출력)."""
    names = ["mimetype"] + [n for n in parts if n != "mimetype"]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name in names:
            zi = zipfile.ZipInfo(name, FIXED_TIME)
            zi.compress_type = zipfile.ZIP_STORED if name in STORED else zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            zi.create_system = 0
            z.writestr(zi, parts[name])
    return buf.getvalue()
