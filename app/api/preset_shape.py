"""OpenAPI 스펙에 보여 줄 모양(ExportPreset). 동작은 그대로다: 값은 여전히 dict로 받고,
서버 검증은 ExportPreset.from_dict가 한다(일부만 보내도 되고, 잘못된 값은 422).
스펙을 읽는 쪽(bolt.new 등)이 설정 화면을 만들 수 있게 항목 이름과 종류만 알려 준다."""
from typing import Annotated, Any

from pydantic import TypeAdapter, WithJsonSchema

from ..export.hwpx import ExportPreset


def _inline(schema: dict) -> dict:
    """$defs 참조를 그 자리에 풀어 넣는다(모양이 중첩만 있고 순환이 없다)."""
    defs = schema.get("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                target = walk(dict(defs[ref.rsplit("/", 1)[1]]))
                return {**target, **{k: walk(v) for k, v in node.items() if k != "$ref"}}
            return {k: walk(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)


def _shape(mode: str) -> dict:
    try:
        return _inline(TypeAdapter(ExportPreset).json_schema(mode=mode))
    except Exception:  # 스펙 설명용이므로 실패해도 앱은 뜬다
        return {"type": "object"}


# 요청: 일부 항목만 보내도 된다(빠진 항목은 기본값).
PresetValue = Annotated[dict[str, Any], WithJsonSchema(_shape("validation"), mode="validation")]
# 응답: 모든 항목이 항상 들어 있다.
PresetValueOut = Annotated[dict[str, Any], WithJsonSchema(_shape("serialization"), mode="serialization")]
