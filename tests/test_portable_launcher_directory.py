import sys

import pytest

from terralocal import cli
from terralocal.launcher import window


@pytest.mark.parametrize("marker", ["settings.json", "terralocal.sqlite3"])
def test_dropping_prepared_directory_uses_that_save(tmp_path, monkeypatch, marker):
    folder = tmp_path / "原有 存档"
    folder.mkdir()
    (folder / marker).write_bytes(b"{}" if marker == "settings.json" else b"")
    default = tmp_path / "unused"
    seen = []
    monkeypatch.setenv("TERRALOCAL_DATA_DIR", str(default))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "argv", ["TerraLocal.exe", str(folder)])
    monkeypatch.setattr(window, "launch", lambda settings: seen.append(settings.data_dir))
    assert cli.main() == 0
    assert seen == [folder.resolve()]
    assert not default.exists()


def test_dropping_unrelated_directory_creates_no_files(tmp_path, monkeypatch, capsys):
    source = tmp_path / "tables"
    source.mkdir()
    (source / "item_table.json").write_text("{}")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "argv", ["TerraLocal.exe", str(source)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
    assert "存档目录" in capsys.readouterr().err
    assert {path.name for path in source.iterdir()} == {"item_table.json"}
