"""Presentation DTOs for Fonfon command output.

These carry *policy* results (status) and are what the renderers and the
exit-code logic consume. Domain services return their own fact DTOs; the
per-command use-case maps those into these types.
"""

from enum import StrEnum

from pydantic import BaseModel


class CheckStatus(StrEnum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"
    INFO = "info"
    SKIP = "skip"


class CheckItem(BaseModel):
    key: str
    label: str
    status: CheckStatus
    detail: str | None = None


class CheckSection(BaseModel):
    title: str
    items: list[CheckItem]


class CheckReport(BaseModel):
    sections: list[CheckSection]

    @property
    def ok(self) -> bool:
        """True unless any item failed. WARN/INFO/SKIP do not fail the gate."""
        return not any(
            item.status is CheckStatus.FAIL
            for section in self.sections
            for item in section.items
        )
