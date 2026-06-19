from fonfon.system.systemctl import Systemctl
from tests.fakes import completed


def _sc(**outcomes):
    # outcomes maps the systemctl subcommand verb -> CompletedProcess
    def run(args, timeout=10):
        verb = args[1]  # ["systemctl", "<verb>", "<unit>"]
        return outcomes[verb]

    return Systemctl(run=run)


def test_is_enabled_true_on_zero_exit_and_enabled():
    sc = _sc(**{"is-enabled": completed([], 0, "enabled\n")})
    assert sc.is_enabled("ssh") is True


def test_is_enabled_false_on_disabled():
    sc = _sc(**{"is-enabled": completed([], 1, "disabled\n")})
    assert sc.is_enabled("docker") is False


def test_is_active_true_on_active():
    sc = _sc(**{"is-active": completed([], 0, "active\n")})
    assert sc.is_active("ssh") is True


def test_is_active_false_on_inactive():
    sc = _sc(**{"is-active": completed([], 3, "inactive\n")})
    assert sc.is_active("docker") is False


def test_exists_false_when_not_found():
    sc = _sc(**{"is-enabled": completed([], 1, "", "Failed to get unit ... not-found")})
    assert sc.exists("nope") is False
