"""Tests for the run_setup use-case and its policy."""

from fonfon.models_setup import SetupStatus
from fonfon.services.setup import build_steps, run_setup, run_step
from fonfon.services.setup_steps import SetupStep


class FakeStep(SetupStep):
    def __init__(self, title, satisfied=False, boom=False):
        self.title = title
        self._satisfied = satisfied
        self._boom = boom
        self.applied = False

    def is_satisfied(self):
        return self._satisfied

    def apply(self):
        if self._boom:
            raise RuntimeError("nope")
        self.applied = True


def test_satisfied_step_is_skipped():
    r = run_step(FakeStep("X", satisfied=True))
    assert r.status is SetupStatus.SKIPPED


def test_unsatisfied_step_applies_and_is_installed():
    step = FakeStep("X")
    r = run_step(step)
    assert r.status is SetupStatus.INSTALLED and step.applied is True


def test_failing_step_is_failed_with_detail():
    r = run_step(FakeStep("X", boom=True))
    assert r.status is SetupStatus.FAILED and "nope" in r.detail


def test_build_steps_order_and_titles():
    titles = [s.title for s in build_steps("jon")]
    assert titles == ["User", "Docker", "Docker group", "Tailscale", "pipx", "sdci"]


def test_run_setup_calls_on_result_per_step(monkeypatch):
    steps = [FakeStep("A"), FakeStep("B", satisfied=True), FakeStep("C")]
    monkeypatch.setattr("fonfon.services.setup.build_steps", lambda u: steps)
    collected = []
    report = run_setup("x", on_result=collected.append)
    assert len(collected) == 3
    assert [r.title for r in collected] == ["A", "B", "C"]
    assert collected == report.steps
