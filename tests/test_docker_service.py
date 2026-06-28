"""Tests for DockerService and DockerReport."""

from fonfon.services.docker_service import DockerService


class FakeDocker:
    def __init__(self, available=True, socket=None, inspect=None, networks=()):
        self._available = available
        # socket status follows CLI presence unless overridden; a bool is
        # accepted as shorthand for "ready"/"down".
        if socket is None:
            self._socket = "ready" if available else "down"
        elif isinstance(socket, bool):
            self._socket = "ready" if socket else "down"
        else:
            self._socket = socket
        self._inspect = inspect
        self._networks = set(networks)

    def cli_present(self):
        return self._available

    def socket_status(self):
        return self._socket

    def inspect_container(self, name):
        return self._inspect

    def network_exists(self, name):
        return name in self._networks


def test_docker_absent_marks_not_installed():
    report = (
        DockerService(docker=FakeDocker(available=False))
        .for_service("traefik")
        .ensure_listening(host="0.0.0.0", ports=[80, 443])
    )
    assert report.docker_installed is False
    assert report.present is False


def test_traefik_listening():
    inspect = {
        "Name": "/traefik",
        "State": {"Running": True},
        "NetworkSettings": {
            "Ports": {
                "80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "80"}],
                "443/tcp": [{"HostIp": "0.0.0.0", "HostPort": "443"}],
            },
            "Networks": {"web": {}},
        },
    }
    report = (
        DockerService(docker=FakeDocker(inspect=inspect))
        .for_service("traefik")
        .ensure_listening(host="0.0.0.0", ports=[80, 443])
    )
    assert report.docker_installed is True
    assert report.socket_ready is True
    assert report.present is True
    assert report.running is True
    assert report.listening == {80: True, 443: True}


def test_socket_not_ready_short_circuits():
    """CLI installed but daemon down: socket_ready False, nothing inspected."""
    report = (
        DockerService(docker=FakeDocker(available=True, socket=False))
        .for_service("traefik")
        .ensure_listening(host="0.0.0.0", ports=[80, 443], network="traefik")
    )
    assert report.docker_installed is True
    assert report.socket_ready is False
    assert report.socket_reason == "down"
    assert report.present is False
    assert report.running is False
    assert report.network_present is False
    assert report.listening == {80: False, 443: False}


def test_socket_permission_denied_is_reported():
    report = (
        DockerService(docker=FakeDocker(available=True, socket="denied"))
        .for_service("traefik")
        .ensure_listening(host="0.0.0.0", ports=[80])
    )
    assert report.docker_installed is True
    assert report.socket_ready is False
    assert report.socket_reason == "denied"


def test_present_but_stopped_is_not_running():
    inspect = {"State": {"Running": False}, "NetworkSettings": {"Ports": {}}}
    report = (
        DockerService(docker=FakeDocker(inspect=inspect))
        .for_service("traefik")
        .ensure_listening(host="0.0.0.0", ports=[80])
    )
    assert report.present is True
    assert report.running is False


def test_traefik_absent_when_inspect_none():
    report = (
        DockerService(docker=FakeDocker(inspect=None))
        .for_service("traefik")
        .ensure_listening(host="0.0.0.0", ports=[80])
    )
    assert report.present is False
    assert report.listening == {80: False}


def test_port_not_listening_when_host_port_mismatch():
    """Port binding exists but on wrong host port -> not listening."""
    inspect = {
        "NetworkSettings": {
            "Ports": {
                "80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}],
            },
            "Networks": {},
        }
    }
    report = (
        DockerService(docker=FakeDocker(inspect=inspect))
        .for_service("traefik")
        .ensure_listening(host="0.0.0.0", ports=[80])
    )
    assert report.listening == {80: False}


def test_port_value_none_not_raises_and_returns_false():
    """'80/tcp': null — exposed but not published."""
    inspect = {"NetworkSettings": {"Ports": {"80/tcp": None}, "Networks": {}}}
    report = (
        DockerService(docker=FakeDocker(available=True, inspect=inspect))
        .for_service("svc")
        .ensure_listening("0.0.0.0", [80])
    )
    assert report.listening == {80: False}


def test_port_key_absent_returns_false():
    """Port requested but entirely absent from the Ports dict."""
    inspect = {"NetworkSettings": {"Ports": {}, "Networks": {}}}
    report = (
        DockerService(docker=FakeDocker(available=True, inspect=inspect))
        .for_service("svc")
        .ensure_listening("0.0.0.0", [80])
    )
    assert report.listening == {80: False}


def test_loopback_only_binding_not_listening():
    inspect = {
        "NetworkSettings": {
            "Ports": {"80/tcp": [{"HostIp": "127.0.0.1", "HostPort": "80"}]},
            "Networks": {},
        }
    }
    report = (
        DockerService(docker=FakeDocker(inspect=inspect))
        .for_service("traefik")
        .ensure_listening("0.0.0.0", [80])
    )
    assert report.listening == {80: False}


def test_all_interfaces_binding_is_listening():
    inspect = {
        "NetworkSettings": {
            "Ports": {"80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "80"}]},
            "Networks": {},
        }
    }
    report = (
        DockerService(docker=FakeDocker(inspect=inspect))
        .for_service("traefik")
        .ensure_listening("0.0.0.0", [80])
    )
    assert report.listening == {80: True}


def test_network_present_true_when_named_network_exists():
    inspect = {"NetworkSettings": {"Ports": {}, "Networks": {}}}
    report = (
        DockerService(docker=FakeDocker(inspect=inspect, networks=["traefik"]))
        .for_service("traefik")
        .ensure_listening("0.0.0.0", [], network="traefik")
    )
    assert report.network_present is True
    assert report.network_name == "traefik"


def test_network_present_false_when_absent():
    inspect = {"NetworkSettings": {"Ports": {}, "Networks": {}}}
    report = (
        DockerService(docker=FakeDocker(inspect=inspect))
        .for_service("traefik")
        .ensure_listening("0.0.0.0", [], network="traefik")
    )
    assert report.network_present is False


def test_network_checked_even_when_container_absent():
    report = (
        DockerService(docker=FakeDocker(inspect=None, networks=["traefik"]))
        .for_service("traefik")
        .ensure_listening("0.0.0.0", [80], network="traefik")
    )
    assert report.present is False
    assert report.network_present is True


def test_dashboard_tailnet_only_when_bound_to_tailnet_ip():
    inspect = {
        "NetworkSettings": {
            "Ports": {"8080/tcp": [{"HostIp": "100.64.0.1", "HostPort": "8080"}]},
            "Networks": {},
        }
    }
    report = (
        DockerService(docker=FakeDocker(inspect=inspect))
        .for_service("traefik")
        .ensure_listening("0.0.0.0", [], dashboard_port=8080, tailnet_ip="100.64.0.1")
    )
    assert report.dashboard_tailnet_only is True
    assert report.dashboard_public is False


def test_dashboard_public_when_bound_to_all_interfaces():
    inspect = {
        "NetworkSettings": {
            "Ports": {"8080/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}]},
            "Networks": {},
        }
    }
    report = (
        DockerService(docker=FakeDocker(inspect=inspect))
        .for_service("traefik")
        .ensure_listening("0.0.0.0", [], dashboard_port=8080, tailnet_ip="100.64.0.1")
    )
    assert report.dashboard_public is True
    assert report.dashboard_tailnet_only is False


def test_dashboard_not_tailnet_only_when_tailnet_ip_unknown():
    inspect = {
        "NetworkSettings": {
            "Ports": {"8080/tcp": [{"HostIp": "100.64.0.1", "HostPort": "8080"}]},
            "Networks": {},
        }
    }
    report = (
        DockerService(docker=FakeDocker(inspect=inspect))
        .for_service("traefik")
        .ensure_listening("0.0.0.0", [], dashboard_port=8080, tailnet_ip=None)
    )
    assert report.dashboard_tailnet_only is False
    assert report.dashboard_public is False


def test_dashboard_unpublished_gives_both_false():
    inspect = {"NetworkSettings": {"Ports": {}, "Networks": {}}}
    report = (
        DockerService(docker=FakeDocker(inspect=inspect))
        .for_service("traefik")
        .ensure_listening("0.0.0.0", [], dashboard_port=8080, tailnet_ip="100.64.0.1")
    )
    assert report.dashboard_public is False
    assert report.dashboard_tailnet_only is False
