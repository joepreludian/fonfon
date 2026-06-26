from fonfon.services.traefik_paths import traefik_paths


def test_traefik_paths_under_user_home():
    paths = traefik_paths("deploy")
    assert paths.base == "/home/deploy/services/traefik"
    assert paths.acme == "/home/deploy/services/traefik/acme"
    assert paths.dynamic == "/home/deploy/services/traefik/dynamic"
    assert paths.compose_file == "/home/deploy/services/traefik/docker-compose.yml"
    assert paths.static_config == "/home/deploy/services/traefik/traefik.yml"
