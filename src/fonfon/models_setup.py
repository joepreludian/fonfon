"""Presentation DTOs for `fonfon setup`."""

from enum import StrEnum

from pydantic import BaseModel


class SetupStatus(StrEnum):
    INSTALLED = "installed"
    SKIPPED = "skipped"
    FAILED = "failed"


class SdciDeployment(BaseModel):
    base_dir: str
    tasks_dir: str
    uploads_dir: str
    token: str


class TraefikDeployment(BaseModel):
    compose_file: str
    network: str
    dashboard_url: str
    cert_email: str


class StepResult(BaseModel):
    title: str
    status: SetupStatus
    detail: str | None = None
    deployment: SdciDeployment | TraefikDeployment | None = None


class SetupReport(BaseModel):
    steps: list[StepResult]

    @property
    def ok(self) -> bool:
        return not any(s.status is SetupStatus.FAILED for s in self.steps)
