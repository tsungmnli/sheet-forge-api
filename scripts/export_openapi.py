"""bolt.new 전달용: 서버를 띄우지 않고 앱 객체에서 OpenAPI 스펙(JSON)을 저장합니다.

sheet-forge-api 폴더에 scripts/export_openapi.py로 두고 실행합니다.
  uv run python scripts/export_openapi.py                 # smoke/openapi.json (.gitignore에 들어 있음)
  uv run python scripts/export_openapi.py --out 경로.json
저장 후 경로 수, 웹에 노출하면 안 되는 이름(header, HEADER_PENDING)이 없는지, 그리고 bolt.new 전달 전 점검(응답 모양 없음·느슨한 object·긴 operationId)을 출력합니다.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.main import app  # noqa: E402


def _bare_object(sch: dict) -> bool:
    """모양이 정해지지 않은 object(properties 없음). anyOf 안의 것도 본다."""
    if not isinstance(sch, dict):
        return False
    if sch.get("type") == "object" and not sch.get("properties"):
        return True
    return any(_bare_object(x) for x in sch.get("anyOf", []) + sch.get("items", {}).get("anyOf", []))


def lint(spec: dict) -> None:
    """bolt.new가 타입을 정확히 만들 수 있는지 본다. 결과는 참고용이며 파일은 바꾸지 않는다."""
    no_schema, long_ids = [], []
    for path, methods in spec.get("paths", {}).items():
        for method, op in methods.items():
            tag = f"{method.upper()} {path}"
            oid = op.get("operationId", "")
            if len(oid) > 60:
                long_ids.append(oid)
            ok = {c: r for c, r in op.get("responses", {}).items() if c.startswith("2")}
            if not ok or all(c == "204" for c in ok):
                continue
            has = any("schema" in m for r in ok.values() for m in r.get("content", {}).values())
            if not has:
                no_schema.append(tag)
    bare = []
    for name, sch in spec.get("components", {}).get("schemas", {}).items():
        for field, p in (sch.get("properties") or {}).items():
            if _bare_object(p):
                bare.append(f"{name}.{field}")
    print("\n[bolt.new 전달 전 점검]")
    print(f"  성공 응답 모양이 없는 동작: {len(no_schema)}개")
    for x in no_schema:
        print(f"    - {x}")
    print(f"  모양이 정해지지 않은 object 필드: {len(bare)}개")
    for x in bare:
        print(f"    - {x}")
    print(f"  operationId가 60자를 넘는 동작: {len(long_ids)}개" + (f" (예: {long_ids[0]})" if long_ids else ""))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="smoke/openapi.json")
    args = ap.parse_args()
    spec = app.openapi()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(spec, ensure_ascii=False, indent=2)
    out.write_text(text, encoding="utf-8")
    ops = sum(len(v) for v in spec.get("paths", {}).values())
    print(f"저장: {out} ({len(text) // 1024} KB), 경로 {len(spec.get('paths', {}))}개, 동작 {ops}개")
    for word in ("HeaderIn", "HEADER_PENDING", '"header"'):
        print(f"  {word}: {'있음 <- 확인 필요' if word in text else '없음'}")
    lint(spec)


if __name__ == "__main__":
    main()
