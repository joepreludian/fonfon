from fonfon.models_setup import SetupReport, SetupStatus, StepResult


def _report(*statuses):
    return SetupReport(
        steps=[StepResult(title=f"S{i}", status=s) for i, s in enumerate(statuses)]
    )


def test_status_values():
    assert SetupStatus.INSTALLED == "installed"
    assert SetupStatus.FAILED == "failed"


def test_ok_true_without_failures():
    assert _report(SetupStatus.INSTALLED, SetupStatus.SKIPPED).ok is True


def test_ok_false_with_failure():
    assert _report(SetupStatus.INSTALLED, SetupStatus.FAILED).ok is False


def test_step_result_token_defaults_none():
    r = StepResult(title="x", status=SetupStatus.SKIPPED)
    assert r.token is None


def test_step_result_token_roundtrips_in_dump():
    r = StepResult(title="sdci config", status=SetupStatus.INSTALLED, token="abc123")
    assert r.model_dump()["token"] == "abc123"
