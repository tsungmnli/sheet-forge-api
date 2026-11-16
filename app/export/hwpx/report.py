"""ExportReport (설계 13장)."""
from dataclasses import dataclass, field, asdict

SEVERITIES = ("info", "warn", "error")


@dataclass(frozen=True)
class ReportItem:
    code: str
    severity: str
    message: str
    problem_id: str | None = None
    where: str | None = None


@dataclass
class ExportReport:
    items: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    layout: dict = field(default_factory=dict)
    effective_preset: dict = field(default_factory=dict)

    def add(self, code, severity, message, problem_id=None, where=None):
        assert severity in SEVERITIES
        self.items.append(ReportItem(code, severity, message, problem_id, where))

    @property
    def status(self) -> str:
        return "warnings" if any(i.severity in ("warn", "error") for i in self.items) else "ok"

    def codes(self) -> list:
        return [i.code for i in self.items]

    def to_dict(self) -> dict:
        return {"status": self.status, "items": [asdict(i) for i in self.items], "stats": self.stats,
                "layout": self.layout, "effective_preset": self.effective_preset}
