"""웹 화면에 그대로 써도 되는 쉬운 문장 표 (웹 REST API 설계 3.1·8장).

code는 웹의 분기용이고 화면에 노출하지 않는다. 표에 없는 code는 일반 문장을 쓴다.
"""

GENERIC = "문제가 생겼어요. 잠시 뒤 다시 시도해 주세요."

MESSAGES = {
    "NOT_FOUND": "찾을 수 없어요. 이미 지웠거나 없는 항목일 수 있어요.",
    "VERSION_CONFLICT": "다른 화면에서 먼저 고쳤어요. 새로 불러올까요?",
    "VERSION_REQUIRED": "화면을 새로 불러온 뒤 다시 시도해 주세요.",
    "PROBLEM_CONFIRMED": "확인을 마친 문제는 바로 고칠 수 없어요. '다시 확인하기'를 먼저 눌러 주세요.",
    "PROBLEM_BUSY": "지금 문제를 읽는 중이에요. 끝난 뒤에 고칠 수 있어요.",
    "MATH_UNSUPPORTED": "아직 한글 수식으로 바꿀 수 없는 수식이 있어요.",
    "EMPTY_PROBLEM": "문제 내용이 비어 있어요.",
    "SEGMENT_HAS_PROBLEM": "이미 읽은 문제가 있는 칸이에요. 문제를 먼저 지워 주세요.",
    "FIGURE_REF_INVALID": "이 문제의 그림이 아니에요.",
    "PHOTO_UNSUPPORTED": "이 사진 형식은 읽을 수 없어요. JPG, PNG, WebP, HEIC 사진을 올려 주세요.",
    "PHOTO_TOO_LARGE": "사진이 너무 커요. 20MB 이하 사진을 올려 주세요.",
    "ORIGINAL_EXPIRED": "원본 사진 보관 기간이 지나서 보정을 다시 할 수 없어요.",
    "PARENT_IN_TRASH": "먼저 위 단계(시험지 등)를 휴지통에서 복구해 주세요.",
    "READ_LIMIT": "오늘 읽기 한도에 도달했어요. 직접 입력은 계속할 수 있어요.",
    "TOO_MANY_SEGMENTS": "한 번에 읽을 수 있는 문제 수를 넘었어요. 나눠서 읽어 주세요.",
    "DB_UNAVAILABLE": "잠시 문제가 생겼어요. 조금 뒤에 다시 시도해 주세요.",
    "STORAGE_UNAVAILABLE": "사진 저장소에 잠시 닿지 못했어요. 조금 뒤에 다시 시도해 주세요.",
    "TOO_MANY_PROBLEMS": "문제지에 담을 수 있는 문제 수를 넘었어요.",
    "PRESET_BUILTIN": "기본으로 들어 있는 모양은 고치거나 지울 수 없어요.",
    "TOO_MANY_PAGES": "시험지 한 건에는 사진을 30장까지 올릴 수 있어요.",
    "REQUEST_INVALID": "요청이 올바르지 않아요. 화면을 새로 불러와 주세요.",
    "INTERNAL_ERROR": GENERIC,
}


def friendly(code: str, default: str | None = None) -> str:
    return MESSAGES.get(code, default or GENERIC)
