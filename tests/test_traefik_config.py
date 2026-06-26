from fonfon.services.traefik_config import (
    TRAEFIK_IMAGE,
    TRAEFIK_NETWORK,
    render_compose,
    render_static_config,
)
from fonfon.services.traefik_paths import traefik_paths


def test_static_config_disables_expose_by_default_and_sets_resolver():
    out = render_static_config("you@example.com")
    assert "exposedByDefault: false" in out
    assert "email: you@example.com" in out
    assert "httpChallenge:" in out
    assert "entryPoint: web" in out
    assert "storage: /acme/acme.json" in out
    assert f"network: {TRAEFIK_NETWORK}" in out
    assert "insecure: true" in out


def test_static_config_redirects_web_to_websecure():
    out = render_static_config("you@example.com")
    assert 'address: ":80"' in out
    assert 'address: ":443"' in out
    assert "to: websecure" in out
    assert "scheme: https" in out


def test_compose_pins_image_and_binds_dashboard_to_tailnet():
    paths = traefik_paths("deploy")
    out = render_compose("100.64.0.1", paths)
    assert f"image: {TRAEFIK_IMAGE}" in out
    assert TRAEFIK_IMAGE == "traefik:v3.7.5"
    assert '"100.64.0.1:8080:8080"' in out
    assert '"80:80"' in out
    assert '"443:443"' in out


def test_compose_mounts_config_and_uses_external_network():
    paths = traefik_paths("deploy")
    out = render_compose("100.64.0.1", paths)
    assert f"{paths.static_config}:/etc/traefik/traefik.yml:ro" in out
    assert f"{paths.dynamic}:/etc/traefik/dynamic:ro" in out
    assert f"{paths.acme}:/acme" in out
    assert "/var/run/docker.sock:/var/run/docker.sock:ro" in out
    assert "external: true" in out
