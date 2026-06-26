import pytest

from fonfon.system.docker_compose import DockerCompose
from tests.fakes import completed


def test_up_runs_docker_compose_up_detached():
    seen = {}

    def run(args, timeout=10, env=None):
        seen["args"] = args
        seen["timeout"] = timeout
        return completed(args, 0, "")

    DockerCompose(run=run).up("/srv/traefik/docker-compose.yml")
    assert seen["args"] == [
        "docker",
        "compose",
        "-f",
        "/srv/traefik/docker-compose.yml",
        "up",
        "-d",
    ]
    assert seen["timeout"] >= 600


def test_up_raises_on_failure():
    def run(args, timeout=10, env=None):
        return completed(args, 1, "", "compose error")

    with pytest.raises(RuntimeError, match="compose error"):
        DockerCompose(run=run).up("/srv/traefik/docker-compose.yml")
