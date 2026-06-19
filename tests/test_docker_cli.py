from fonfon.system.docker_cli import DockerCli
from tests.fakes import completed


def test_is_available_true_on_zero_exit():
    docker = DockerCli(run=lambda args, timeout=10: completed(args, 0, "27.3.1"))
    assert docker.is_available() is True


def test_inspect_container_returns_none_when_absent():
    docker = DockerCli(
        run=lambda args, timeout=10: completed(args, 1, "", "No such object")
    )
    assert docker.inspect_container("traefik") is None


def test_inspect_container_parses_json():
    payload = '[{"Name":"/traefik","NetworkSettings":{}}]'
    docker = DockerCli(run=lambda args, timeout=10: completed(args, 0, payload))
    data = docker.inspect_container("traefik")
    assert data["Name"] == "/traefik"
