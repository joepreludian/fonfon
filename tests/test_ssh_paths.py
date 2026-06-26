from fonfon.services.ssh_paths import ssh_paths


def test_ssh_paths_under_user_home():
    paths = ssh_paths("deploy")
    assert paths.ssh_dir == "/home/deploy/.ssh"
    assert paths.authorized_keys == "/home/deploy/.ssh/authorized_keys"
