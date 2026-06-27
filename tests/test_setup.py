"""Tests for the run_setup use-case and its policy."""

from fonfon.models_setup import SdciDeployment, SetupStatus
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
    monkeypatch.setattr(
        "fonfon.services.setup.build_steps",
        lambda u, k=None, c=None, g=None, run=None: steps,
    )
    collected = []
    report = run_setup("x", on_result=collected.append)
    assert len(collected) == 3
    assert [r.title for r in collected] == ["A", "B", "C"]
    assert collected == report.steps


def test_run_setup_calls_on_step_start_per_step(monkeypatch):
    steps = [FakeStep("A"), FakeStep("B", satisfied=True), FakeStep("C")]
    monkeypatch.setattr(
        "fonfon.services.setup.build_steps",
        lambda u, k=None, c=None, g=None, run=None: steps,
    )
    started = []
    results = []
    run_setup("x", on_step_start=started.append, on_result=results.append)
    assert [s.title for s in started] == ["A", "B", "C"]
    assert [r.title for r in results] == ["A", "B", "C"]


def test_run_setup_on_step_start_called_before_on_result(monkeypatch):
    steps = [FakeStep("A")]
    monkeypatch.setattr(
        "fonfon.services.setup.build_steps",
        lambda u, k=None, c=None, g=None, run=None: steps,
    )
    events = []
    run_setup(
        "x",
        on_step_start=lambda s: events.append(("start", s.title)),
        on_result=lambda r: events.append(("result", r.title)),
    )
    assert events == [("start", "A"), ("result", "A")]


def test_run_step_propagates_deployment_from_step():
    class DeployStep(SetupStep):
        title = "T"

        def is_satisfied(self):
            return False

        def apply(self):
            self.deployment = SdciDeployment(
                base_dir="b", tasks_dir="t", uploads_dir="u", token="abc"
            )

    r = run_step(DeployStep())
    assert r.status is SetupStatus.INSTALLED
    assert r.deployment.token == "abc"


def test_run_step_deployment_none_for_plain_step():
    assert run_step(FakeStep("X")).deployment is None


def test_build_steps_with_auth_key_appends_service_steps():
    titles = [s.title for s in build_steps("jon", "tskey-abc")]
    assert titles == [
        "User",
        "Docker",
        "Docker group",
        "Tailscale",
        "pipx",
        "sdci",
        "Tailscale up",
        "sdci dirs",
        "sdci config",
    ]


def test_build_steps_without_auth_key_is_install_only():
    titles = [s.title for s in build_steps("jon")]
    assert titles == ["User", "Docker", "Docker group", "Tailscale", "pipx", "sdci"]


def test_build_steps_with_auth_key_and_cert_email_appends_traefik_steps():
    titles = [s.title for s in build_steps("jon", "tskey-abc", "you@example.com")]
    assert titles == [
        "User",
        "Docker",
        "Docker group",
        "Tailscale",
        "pipx",
        "sdci",
        "Tailscale up",
        "sdci dirs",
        "sdci config",
        "Traefik dirs",
        "Traefik network",
        "Traefik",
    ]


def test_build_steps_with_auth_key_but_no_cert_email_skips_traefik():
    titles = [s.title for s in build_steps("jon", "tskey-abc")]
    assert "Traefik" not in titles
    assert titles[-1] == "sdci config"


def test_build_steps_cert_email_without_auth_key_adds_nothing():
    # Traefik needs the tailnet IP, so without an auth key it must not appear.
    titles = [s.title for s in build_steps("jon", None, "you@example.com")]
    assert titles == ["User", "Docker", "Docker group", "Tailscale", "pipx", "sdci"]


def test_build_steps_with_github_user_appends_ssh_steps_last():
    titles = [s.title for s in build_steps("jon", "tskey-abc", None, "octocat")]
    assert titles == [
        "User",
        "Docker",
        "Docker group",
        "Tailscale",
        "pipx",
        "sdci",
        "Tailscale up",
        "sdci dirs",
        "sdci config",
        "Authorized keys",
        "SSH hardening",
    ]


def test_build_steps_github_user_without_auth_key_still_hardens():
    # SSH hardening only needs the operator user, not the tailnet.
    titles = [s.title for s in build_steps("jon", None, None, "octocat")]
    assert titles == [
        "User",
        "Docker",
        "Docker group",
        "Tailscale",
        "pipx",
        "sdci",
        "Authorized keys",
        "SSH hardening",
    ]


def test_build_steps_without_github_user_has_no_ssh_steps():
    titles = [s.title for s in build_steps("jon", "tskey-abc")]
    assert "Authorized keys" not in titles
    assert "SSH hardening" not in titles


def test_build_steps_all_flags_order_ssh_after_traefik():
    titles = [
        s.title for s in build_steps("jon", "tskey-abc", "you@example.com", "octocat")
    ]
    assert titles[-2:] == ["Authorized keys", "SSH hardening"]
    assert "Traefik" in titles
