from fonfon.system import probes
from tests.fakes import completed


def test_parse_os_release_extracts_id_and_pretty_name():
    text = 'PRETTY_NAME="Debian GNU/Linux 12 (bookworm)"\nID=debian\nVERSION_ID="12"\n'
    info = probes.parse_os_release(text)
    assert info["ID"] == "debian"
    assert info["PRETTY_NAME"] == "Debian GNU/Linux 12 (bookworm)"


def test_interfaces_parses_ip_json_addr():
    ip_json = (
        '[{"ifname":"lo","addr_info":[{"family":"inet","local":"127.0.0.1"}]},'
        '{"ifname":"eth0","addr_info":[{"family":"inet","local":"203.0.113.5"}]},'
        '{"ifname":"tailscale0","addr_info":[{"family":"inet","local":"100.101.102.103"}]}]'
    )

    def run(args, timeout=10):
        return completed(args, stdout=ip_json)

    result = probes.interfaces(run=run)
    # lo excluded
    assert result == {"eth0": "203.0.113.5", "tailscale0": "100.101.102.103"}


def test_public_ip_returns_stripped_body():
    def opener(url, timeout):
        return _FakeResp(b"203.0.113.5\n")

    assert probes.public_ip(opener=opener) == "203.0.113.5"


def test_public_ip_returns_none_on_error():
    def opener(url, timeout):
        raise OSError("no network")

    assert probes.public_ip(opener=opener) is None


class _FakeResp:
    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False
