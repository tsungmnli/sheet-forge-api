"""B5-5c: read_v5 프롬프트와 읽기 스키마의 box·table 블록 (LLM 호출 없음)."""
from app.recognition.llm.read import PROMPT_PATH, PROMPT_VERSION, load_prompt
from app.recognition.llm.schemas import READ_SCHEMA


def test_prompt_version_and_placeholder():
    assert PROMPT_VERSION == "read_v5"
    assert PROMPT_PATH.name == "read_v5.md"
    assert PROMPT_PATH.read_text(encoding="utf-8").count("{{VOCAB}}") == 1
    text = load_prompt()
    assert "{{VOCAB}}" not in text and "\r" not in text


def test_prompt_describes_box_and_table_blocks():
    text = load_prompt()
    for key in ("type=box", "type=table", "rows", "title", "unsupported_block"):
        assert key in text
    assert "(6번 규칙)" in text and "<보기> 상자의 줄마다다" not in text


def test_schema_stem_blocks():
    item = READ_SCHEMA["properties"]["stem"]["items"]
    assert item["required"] == ["type"]
    assert item["properties"]["type"]["enum"] == ["paragraph", "box", "table"]
    assert item["properties"]["title"]["nullable"] is True
    assert item["properties"]["paragraphs"]["items"]["required"] == ["inlines"]
    assert item["properties"]["rows"]["items"]["items"]["items"]["required"] == ["t", "v", "latex"]   # 행 -> 칸 -> 조각
