"""사후 검증 (설계 12장). 실패하면 내부 버그로 보고 파일을 반환하지 않는다."""
import io
import re
import zipfile

from lxml import etree

from .errors import InternalValidationError

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HH = "http://www.hancom.co.kr/hwpml/2011/head"
HC = "http://www.hancom.co.kr/hwpml/2011/core"
OPF = "http://www.idpf.org/2007/opf/"


def validate_package(data: bytes) -> list:
    problems: list = []
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return ["zip을 열 수 없음"]
    infos = z.infolist()
    if not infos or infos[0].filename != "mimetype" or infos[0].compress_type != zipfile.ZIP_STORED:
        problems.append("zip 첫 항목이 무압축 mimetype이 아님")
    xml_docs = {}
    for i in infos:
        if i.filename.endswith((".xml", ".hpf", ".rdf")):
            try:
                xml_docs[i.filename] = etree.fromstring(z.read(i.filename))
            except etree.XMLSyntaxError as ex:
                problems.append(f"{i.filename}: well-formed 아님 ({ex})")
    if problems or "Contents/header.xml" not in xml_docs or "Contents/section0.xml" not in xml_docs:
        return problems or ["header/section0 없음"]
    head, sec = xml_docs["Contents/header.xml"], xml_docs["Contents/section0.xml"]

    def ids_of(tag):
        return [e.get("id") for e in head.iter(f"{{{HH}}}{tag}")]

    para_ids, char_ids = set(ids_of("paraPr")), set(ids_of("charPr"))
    tab_ids = set(ids_of("tabPr"))
    for container, child, label in (("paraProperties", "paraPr", "paraProperties"),
                                    ("charProperties", "charPr", "charProperties"),
                                    ("tabProperties", "tabPr", "tabProperties")):
        for c in head.iter(f"{{{HH}}}{container}"):
            real = len(c.findall(f"{{{HH}}}{child}"))
            if int(c.get("itemCnt")) != real:
                problems.append(f"{label} itemCnt={c.get('itemCnt')} 실제={real}")
    if len(ids_of("paraPr")) != len(para_ids):
        problems.append("paraPr id 중복")
    for ff in head.iter(f"{{{HH}}}fontface"):
        real = len(ff.findall(f"{{{HH}}}font"))
        if int(ff.get("fontCnt")) != real:
            problems.append(f"fontface {ff.get('lang')} fontCnt={ff.get('fontCnt')} 실제={real}")
        fids = [f.get("id") for f in ff.findall(f"{{{HH}}}font")]
        if len(set(fids)) != len(fids):
            problems.append(f"fontface {ff.get('lang')} font id 중복")
    # charPr 0이 가리키는 글꼴 존재
    faces = {ff.get("lang"): {f.get("id") for f in ff.findall(f"{{{HH}}}font")} for ff in head.iter(f"{{{HH}}}fontface")}
    for cp in head.iter(f"{{{HH}}}charPr"):
        ref = cp.find(f"{{{HH}}}fontRef")
        for lang, attr in (("HANGUL", "hangul"), ("LATIN", "latin")):
            if ref is not None and ref.get(attr) not in faces.get(lang, set()):
                problems.append(f"charPr {cp.get('id')}의 fontRef {attr}={ref.get(attr)} 글꼴 없음")
    seen = set()
    for p in sec.iter(f"{{{HP}}}p"):
        if p.get("id") in seen:
            problems.append(f"문단 id 중복 {p.get('id')}")
        seen.add(p.get("id"))
        if p.get("paraPrIDRef") not in para_ids:
            problems.append(f"paraPrIDRef={p.get('paraPrIDRef')} 없음")
        tref = None
    for r in sec.iter(f"{{{HP}}}run"):
        if r.get("charPrIDRef") not in char_ids:
            problems.append(f"charPrIDRef={r.get('charPrIDRef')} 없음")
    # 수식: id·zOrder 고유, 스크립트 존재, sz·baseLine 0 [검증 t6a/t6b], baseUnit 양수
    eq_ids, eq_z = set(), set()
    for e in sec.iter(f"{{{HP}}}equation"):
        if e.get("id") in eq_ids or e.get("id") in seen:
            problems.append(f"수식 id 중복 {e.get('id')}")
        eq_ids.add(e.get("id"))
        if e.get("zOrder") in eq_z:
            problems.append(f"수식 zOrder 중복 {e.get('zOrder')}")
        eq_z.add(e.get("zOrder"))
        script = e.find(f"{{{HP}}}script")
        if script is None or not (script.text or "").strip():
            problems.append(f"수식 {e.get('id')}: 스크립트가 비어 있음")
        sz = e.find(f"{{{HP}}}sz")
        if e.get("baseLine") != "0" or sz is None or sz.get("width") != "0" or sz.get("height") != "0":
            problems.append(f"수식 {e.get('id')}: sz·baseLine이 0이 아님(겹침 위험, t6b)")
        if not (e.get("baseUnit") or "").isdigit() or int(e.get("baseUnit")) <= 0:
            problems.append(f"수식 {e.get('id')}: baseUnit이 올바르지 않음")
    # 그림: id·zOrder 고유, binaryItemIDRef가 manifest에 있음, sz > 0
    hpf = xml_docs.get("Contents/content.hpf")
    manifest_ids = {it.get("id") for it in hpf.iter(f"{{{OPF}}}item")} if hpf is not None else set()
    pic_ids, pic_z = set(), set()
    for e in sec.iter(f"{{{HP}}}pic"):
        if e.get("id") in pic_ids or e.get("id") in eq_ids or e.get("id") in seen:
            problems.append(f"그림 id 중복 {e.get('id')}")
        pic_ids.add(e.get("id"))
        if e.get("zOrder") in pic_z or e.get("zOrder") in eq_z:
            problems.append(f"그림 zOrder 중복 {e.get('zOrder')}")
        pic_z.add(e.get("zOrder"))
        img = e.find(f"{{{HC}}}img")
        if img is None or img.get("binaryItemIDRef") not in manifest_ids:
            problems.append(f"그림 {e.get('id')}: binaryItemIDRef가 manifest에 없음")
        sz = e.find(f"{{{HP}}}sz")
        if sz is None or int(sz.get("width", 0)) <= 0 or int(sz.get("height", 0)) <= 0:
            problems.append(f"그림 {e.get('id')}: sz가 올바르지 않음")
    for pr in head.iter(f"{{{HH}}}paraPr"):
        if pr.get("tabPrIDRef") not in tab_ids:
            problems.append(f"paraPr {pr.get('id')}의 tabPrIDRef={pr.get('tabPrIDRef')} 없음")
    # manifest ↔ 파일 일치
    hpf = xml_docs.get("Contents/content.hpf")
    names = {i.filename for i in infos}
    if hpf is not None:
        for it in hpf.iter("{http://www.idpf.org/2007/opf/}item"):
            if it.get("href") not in names:
                problems.append(f"manifest의 {it.get('href')}가 zip에 없음")
        hrefs = {it.get("href") for it in hpf.iter("{http://www.idpf.org/2007/opf/}item")}
        for n in sorted(names):
            if n.startswith("BinData/") and n not in hrefs:
                problems.append(f"{n}가 manifest에 등록되지 않음")
    return problems


def assert_valid(data: bytes) -> None:
    problems = validate_package(data)
    if problems:
        raise InternalValidationError(problems)
