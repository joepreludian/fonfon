from fonfon.models import CheckItem, CheckReport, CheckSection, CheckStatus


def _report(*statuses: CheckStatus) -> CheckReport:
    items = [
        CheckItem(key=f"k{i}", label=f"L{i}", status=s, detail=None)
        for i, s in enumerate(statuses)
    ]
    return CheckReport(sections=[CheckSection(title="S", items=items)])


def test_status_enum_values_are_lowercase_strings():
    assert CheckStatus.OK.value == "ok"
    assert CheckStatus.FAIL.value == "fail"


def test_report_ok_true_when_no_fail():
    report = _report(
        CheckStatus.OK, CheckStatus.WARN, CheckStatus.INFO, CheckStatus.SKIP
    )
    assert report.ok is True


def test_report_ok_false_when_any_fail():
    report = _report(CheckStatus.OK, CheckStatus.FAIL)
    assert report.ok is False


def test_report_serializes_to_json():
    report = _report(CheckStatus.OK)
    data = report.model_dump_json()
    assert '"status":"ok"' in data.replace(" ", "")
