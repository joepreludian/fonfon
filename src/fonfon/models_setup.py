"""Presentation DTOs for `fonfon setup`."""

from enum import StrEnum

from pydantic import BaseModel


class SetupStatus(StrEnum):
    INSTALLED = "installed"
    SKIPPED = "skipped"
    FAILED = "failed"


class StepResult(BaseModel):
    title: str
    status: SetupStatus
    detail: str | None = None
    token: str | None = None


class SetupReport(BaseModel):
    steps: list[StepResult]

    @property
    def ok(self) -> bool:
        return not any(s.status is SetupStatus.FAILED for s in self.steps)
