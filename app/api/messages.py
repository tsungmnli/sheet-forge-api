"""웹 화면에 그대로 써도 되는 쉬운 문장 표 (웹 REST API 설계 3.1·8장).

code는 웹의 분기용이고 화면에 노출하지 않는다. 표에 없는 code는 일반 문장을 쓴다.
"""

GENERIC = "문제가 생겼어요. 잠시 뒤 다시 시도해 주세요."

MESSAGES = {
    "NOT_AUTHENTICATED": "로그인이 필요해요. 다시 로그인해 주세요.",
    "INVALID_CREDENTIALS": "이메일 또는 비밀번호가 맞지 않아요. 다시 확인해 주세요.",
    "INVITE_INVALID": "초대 링크가 만료됐거나 이미 사용했어요. 초대를 다시 요청해 주세요.",
    "RESET_INVALID": "링크가 만료됐거나 이미 사용했어요. 비밀번호 찾기를 다시 해 주세요.",
    "ALREADY_REGISTERED": "이미 가입한 이메일이에요. 로그인해 주세요.",
    "MAIL_FAILED": "메일을 보내지 못했어요. 잠시 뒤에 다시 시도해 주세요.",
    "NOT_FOUND": "찾을 수 없어요. 이미 지웠거나 없는 항목일 수 있어요.",
    "VERSION_CONFLICT": "다른 화면에서 먼저 고쳤어요. 새로 불러올까요?",
    "VERSION_REQUIRED": "화면을 새로 불러온 뒤 다시 시도해 주세요.",
    "PROBLEM_CONFIRMED": "확인을 마친 문제는 바로 고칠 수 없어요. '다시 확인하기'를 먼저 눌러 주세요.",
    "PROBLEM_BUSY": "지금 문제를 읽는 중이에요. 끝난 뒤에 고칠 수 있어요.",
    "MATH_UNSUPPORTED": "아직 한글 수식으로 바꿀 수 없는 수식이 있어요.",
    "EMPTY_PROBLEM": "문제 내용이 비어 있어요.",
    "SEGMENT_HAS_PROBLEM": "이미 읽은 문제가 있는 칸이에요. 문제를 먼저 지워 주세요.",
    "FIGURE_REF_INVALID": "이 문제의 그림이 아니에요.",
    "FIGURE_IMAGE_TOO_LARGE": "지운 그림이 너무 커요. 그림을 줄여서 다시 시도해 주세요.",
    "FIGURE_IMAGE_INVALID": "지운 그림을 저장할 수 없어요. 다시 시도해 주세요.",
    "FIGURE_NOT_CLEANED": "정리 단계를 고른 그림에서만 지울 수 있어요.",
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


# ---- 내보내기 리포트 문장 표 (웹 REST API 설계 3.1·5.7). 라이브러리의 message는 개발자용이라 웹에는 이 표로 바꿔 준다 ----
REPORT_GENERIC = "한글에서 열어 보면 좋은 곳이에요."

REPORT_MESSAGES = {
    "NOT_CONFIRMED": "확인이 끝나지 않은 문제는 빼고 만들었어요.",
    "UNSUPPORTED_MATH": "한글 수식으로 바꾸지 못한 수식이 있어요. 글자로 넣었으니 한글에서 고쳐 주세요.",
    "MATH_NOTE": "이 수식은 한글에서 한 번 확인해 보면 좋아요.",
    "EQ_AUTO_BROKEN": "긴 수식이라 줄을 나눠 넣었어요.",
    "EQ_TOO_WIDE": "수식이 한 줄에 다 안 들어갈 수 있어요. 한글에서 줄을 나눠 주세요.",
    "TEXT_FORMAT_IGNORED": "굵게·밑줄은 아직 반영하지 않았어요.",
    "CHOICES_NEAR_LIMIT": "선택지가 한 줄에 빠듯해요. 한글에서 줄이 갈라지면 직접 고쳐 주세요.",
    "FIGURE_MISSING": "그림을 불러오지 못해 이 문제를 빼고 만들었어요.",
    "FIGURE_SHRUNK": "그림이 칸보다 커서 칸에 맞춰 줄였어요.",
    "FIGURE_TALL": "그림이 한 쪽보다 길 수 있어요. 한글에서 확인해 주세요.",
    "FONT_NOT_VERIFIED": "고른 글꼴이 없는 컴퓨터에서는 다른 글꼴로 보일 수 있어요.",
    "NOT_IMPLEMENTED": "아직 지원하지 않는 부분이 있어 기본 방식으로 처리했어요.",
}


def report_message(code: str) -> str:
    return REPORT_MESSAGES.get(code, REPORT_GENERIC)


def report_summary(items: list) -> str:
    """리포트 한 줄 요약. 참고(info)는 세지 않는다."""
    n = sum(1 for i in items if i.get("severity") in ("warn", "error"))
    if n == 0:
        return "한글 파일을 만들었어요."
    text = f"한글 파일을 만들었어요. 한글에서 열어 보면 좋은 곳이 {n}군데 있어요."
    if any(i.get("severity") == "error" for i in items):
        text += " 빠진 문제도 있으니 아래를 확인해 주세요."
    return text
