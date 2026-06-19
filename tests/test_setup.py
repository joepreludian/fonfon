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
    monkeypatch.setattr("fonfon.services.setup.build_steps", lambda u, run=None: steps)
    collected = []
    report = run_setup("x", on_result=collected.append)
    assert len(collected) == 3
    assert [r.title for r in collected] == ["A", "B", "C"]
    assert collected == report.steps


def test_run_setup_calls_on_step_start_per_step(monkeypatch):
    steps = [FakeStep("A"), FakeStep("B", satisfied=True), FakeStep("C")]
    monkeypatch.setattr("fonfon.services.setup.build_steps", lambda u, run=None: steps)
    started = []
    results = []
    run_setup("x", on_step_start=started.append, on_result=results.append)
    assert [s.title for s in started] == ["A", "B", "C"]
    assert [r.title for r in results] == ["A", "B", "C"]


def test_run_setup_on_step_start_called_before_on_result(monkeypatch):
    steps = [FakeStep("A")]
    monkeypatch.setattr("fonfon.services.setup.build_steps", lambda u, run=None: steps)
    events = []
    run_setup(
        "x",
        on_step_start=lambda s: events.append(("start", s.title)),
        on_result=lambda r: events.append(("result", r.title)),
    )
    assert events == [("start", "A"), ("result", "A")]


def test_run_step_propagates_token_from_step():
    class TokenStep(SetupStep):
        title = "T"

        def is_satisfied(self):
            return False

        def apply(self):
            self.token = "abc123"

    r = run_step(TokenStep())
    assert r.status is SetupStatus.INSTALLED
    assert r.token == "abc123"


def test_run_step_token_none_for_plain_step():
    r = run_step(FakeStep("X"))
    assert r.token is None
