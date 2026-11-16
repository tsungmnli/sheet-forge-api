"""내보내기 예외. 문제는 ExportReport로 알리고, 내보낼 수 없을 때만 예외를 쓴다(설계 1장 원칙 4)."""


class ExportError(Exception):
    code = "EXPORT_ERROR"


class PresetError(ExportError, ValueError):
    """preset 검증 실패. errors = [(코드, 메시지), ...] (코드는 PRESET_*)."""

    code = "PRESET_INVALID"

    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("; ".join(f"{c}: {m}" for c, m in self.errors))


class EmptyExportError(ExportError):
    code = "EMPTY_EXPORT"


class UnconfirmedProblemError(ExportError):
    code = "NOT_CONFIRMED"


class TemplateError(ExportError):
    code = "TEMPLATE_INVALID"


class InternalValidationError(ExportError):
    """사후 검증(12장) 실패 = 내부 버그. 파일을 반환하지 않는다."""

    code = "INTERNAL_VALIDATION"

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))
