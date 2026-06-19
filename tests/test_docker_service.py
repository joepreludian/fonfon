"""Tests for DockerService and DockerReport."""

from fonfon.services.docker_service import DockerService


class FakeDocker:
    def __init__(self, available=True, inspect=None):
        self._available, self._inspect = available, inspect

    def is_available(self):
        return self._available

    def inspect_container(self, name):
        return self._inspect


def test_docker_absent_marks_not_installed():
    report = (
        DockerService(docker=FakeDocker(available=False))
        .for_service("traefik")
        .ensure_listening(host="0.0.0.0", ports=[80, 443])
    )
    assert report.docker_installed is False
    assert report.present is False


def test_traefik_listening_and_external_network():
    inspect = {
        "Name": "/traefik",
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
    assert report.present is True
    assert report.listening == {80: True, 443: True}
    assert report.external_network is True


def test_traefik_absent_when_inspect_none():
    report = (
        DockerService(docker=FakeDocker(inspect=None))
        .for_service("traefik")
        .ensure_listening(host="0.0.0.0", ports=[80])
    )
    assert report.present is False
    assert report.listening == {80: False}
    assert report.external_network is False


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


def test_only_default_networks_gives_external_network_false():
    inspect = {
        "NetworkSettings": {
            "Ports": {},
            "Networks": {"bridge": {}, "host": {}},
        }
    }
    report = (
        DockerService(docker=FakeDocker(inspect=inspect))
        .for_service("svc")
        .ensure_listening(host="0.0.0.0", ports=[])
    )
    assert report.external_network is False


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
