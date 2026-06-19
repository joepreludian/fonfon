from fonfon.services.systemd_service import SystemdService


class FakeSystemctl:
    def __init__(self, enabled=(), active=(), present=None):
        self._enabled, self._active = set(enabled), set(active)
        self._present = set(present) if present is not None else None

    def is_enabled(self, unit):
        return unit in self._enabled

    def is_active(self, unit):
        return unit in self._active

    def exists(self, unit):
        return unit in self._present if self._present is not None else True


def test_get_status_reports_each_unit():
    svc = SystemdService(systemctl=FakeSystemctl(enabled={"ssh"}, active={"ssh"}))
    report = svc.for_services(["docker", "ssh"]).get_status()
    by_name = {s.name: s for s in report.services}
    assert by_name["ssh"].enabled is True and by_name["ssh"].active is True
    assert by_name["docker"].enabled is False


def test_for_services_is_fluent():
    svc = SystemdService(systemctl=FakeSystemctl())
    assert svc.for_services(["ssh"]) is svc
