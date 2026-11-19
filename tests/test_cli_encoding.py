"""Frozen Windows commands must preserve Unicode when stdout/stderr are piped."""
import io
import json
import sys

from terralocal.cli import main


def run_with_frozen_pipe(monkeypatch, folder, command, stream_name):
    buffer = io.BytesIO()
    pipe = io.TextIOWrapper(buffer, encoding="cp1252", write_through=True)
    try:
        with monkeypatch.context() as context:
            context.setattr(sys, "frozen", True, raising=False)
            context.setattr(sys, "argv", ["TerraLocal", "--data-dir", str(folder), command])
            context.setattr(sys, stream_name, pipe)
            result = main()
        pipe.flush()
        return result, buffer.getvalue()
    finally:
        pipe.detach()


def test_frozen_doctor_outputs_utf8_json_for_unicode_save_path(monkeypatch, tmp_path):
    folder = tmp_path / "中文存档"
    result, raw = run_with_frozen_pipe(monkeypatch, folder, "doctor", "stdout")
    assert result == 1
    assert json.loads(raw.decode("utf8"))["data_dir"] == str(folder.resolve())
    assert not folder.exists()


def test_frozen_backup_error_remains_utf8_and_keeps_the_save_absent(monkeypatch, tmp_path):
    folder = tmp_path / "中文存档"
    result, raw = run_with_frozen_pipe(monkeypatch, folder, "backup", "stderr")
    assert result == 2
    assert "当前目录没有存档" in raw.decode("utf8")
    assert not folder.exists()
