from fonfon.services.sdci_paths import sdci_paths


def test_sdci_paths_derives_from_user():
    p = sdci_paths("preludian")
    assert p.base == "/home/preludian/services/sdci"
    assert p.tasks == "/home/preludian/services/sdci/tasks"
    assert p.uploads == "/home/preludian/services/sdci/uploads"
