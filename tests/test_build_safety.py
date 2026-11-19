"""A build, rebuild, cache clean or failure must never modify installed saves."""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tools import build_release as release

VERSION = "3.4.2"
RUNTIME_FILE = "_internal/dependency/runtime.bin"


def project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "pyproject.toml").write_text(f'[project]\nversion = "{VERSION}"\n', encoding="utf-8")
    for name in ("README.md", "STATUS.md", "CHANGELOG.md"):
        (root / name).write_text("Synthetic release documentation", encoding="utf-8")
    static = root / "terralocal" / "admin" / "static"
    static.mkdir(parents=True)
    (root / "terralocal" / "__main__.py").write_text("pass\n", encoding="utf-8")
    for name in ("index.html", "app.js", "app.css"):
        (static / name).write_text(f"Synthetic packaged {name}", encoding="utf-8")
    install = root / "dist" / "TerraLocal"
    install.mkdir(parents=True)
    (install / "TerraLocal.exe").write_bytes(b"original executable")
    return root, install


def builder(command, *, cwd, check, **options):
    if command[1:] == ["--version"]:
        return subprocess.CompletedProcess(command, 0, stdout=f"{VERSION}\n")
    output = Path(command[command.index("--distpath") + 1]) / "TerraLocal"
    output.mkdir(parents=True)
    (output / "TerraLocal.exe").write_bytes(b"synthetic new executable")
    for index, arg in enumerate(command):
        if arg == "--add-data":
            source, directory = command[index + 1].rsplit(os.pathsep, 1)
            target = output / "_internal" / directory / Path(source).name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    dependency = output / RUNTIME_FILE
    dependency.parent.mkdir(parents=True)
    dependency.write_bytes(b"fixture runtime")
    return subprocess.CompletedProcess(command, 0)


@pytest.mark.parametrize("clean", [False, True])
def test_repeated_builds_leave_physical_portable_data_untouched(tmp_path, monkeypatch, clean):
    root, install = project(tmp_path)
    (install / "data").mkdir()
    database = install / "data" / "terralocal.sqlite3"
    database.write_bytes(b"authoritative game save")
    configuration = install / "data" / "settings.json"
    configuration.write_bytes(b"authoritative settings")
    monkeypatch.setattr(release.subprocess, "run", builder)
    first = release.build_release(root, clean=clean)
    second = release.build_release(root, clean=clean)
    assert first != second and first.is_file() and second.is_file()
    assert first.is_relative_to(root / "dist" / "releases")
    assert database.read_bytes() == b"authoritative game save"
    assert configuration.read_bytes() == b"authoritative settings"
    assert (install / "TerraLocal.exe").read_bytes() == b"original executable"
    info = json.loads((first.parent / "build-manifest.json").read_bytes())
    assert info["version"] == VERSION and info["schema_version"] == 2
    assert info["official_apk_included"] is info["official_resources_included"] is info["client_verified"] is False
    for entry in info["files"]:
        content = (first.parent / entry["path"]).read_bytes()
        assert entry["bytes"] == len(content)
        assert entry["sha256"] == hashlib.sha256(content).hexdigest()
        assert not entry["path"].startswith("data/")


def junction(link, target):
    if os.name != "nt":
        link.symlink_to(target, target_is_directory=True)
        return
    shell = shutil.which("pwsh") or shutil.which("powershell")
    assert shell
    environment = {**os.environ, "TERRALOCAL_TEST_LINK": str(link), "TERRALOCAL_TEST_TARGET": str(target)}
    subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command",
                    "New-Item -ItemType Junction -Path $env:TERRALOCAL_TEST_LINK "
                    "-Target $env:TERRALOCAL_TEST_TARGET | Out-Null"],
                   env=environment, check=True, capture_output=True, text=True)


def test_existing_junction_and_target_survive_clean_build(tmp_path, monkeypatch):
    root, install = project(tmp_path)
    target = root / "player-data"
    target.mkdir()
    (target / "terralocal.sqlite3").write_bytes(b"shared existing save")
    junction(install / "data", target)
    monkeypatch.setattr(release.subprocess, "run", builder)
    release.build_release(root, clean=True)
    assert (install / "data").resolve() == target
    assert (target / "terralocal.sqlite3").read_bytes() == b"shared existing save"


@pytest.mark.parametrize("phase", ["packaging", "executable-validation"])
def test_failed_build_preserves_install_and_does_not_publish_manifest(tmp_path, monkeypatch, phase):
    root, install = project(tmp_path)
    (install / "data").mkdir()
    (install / "data" / "terralocal.sqlite3").write_bytes(b"save before failed build")

    def fail(command, **options):
        if phase == "packaging" or command[1:] == ["--version"]:
            raise subprocess.CalledProcessError(1, command)
        return builder(command, **options)

    monkeypatch.setattr(release.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        release.build_release(root, clean=True)
    assert (install / "data" / "terralocal.sqlite3").read_bytes() == b"save before failed build"
    assert (install / "TerraLocal.exe").read_bytes() == b"original executable"
    assert not list((root / "dist" / "releases").rglob("build-manifest.json"))


@pytest.mark.parametrize("kind", ["data", "external-link"])
def test_build_rejects_embedded_save_or_linked_content(tmp_path, monkeypatch, kind):
    root, _ = project(tmp_path)
    external = root / "authoritative-data"
    external.mkdir()
    (external / "save.sqlite3").write_bytes(b"keep me")
    # Create a real junction before replacing subprocess.run for the builder.
    link = root / "link-ready"
    if kind == "external-link":
        junction(link, external)

    def contaminated(command, **options):
        result = builder(command, **options)
        if command[1:] != ["--version"]:
            bundle = Path(command[command.index("--distpath") + 1]) / "TerraLocal"
            if kind == "data":
                (bundle / "data").mkdir()
                (bundle / "data" / "save.sqlite3").write_bytes(b"unexpected save")
            else:
                link.rename(bundle / "linked-content")
        return result

    monkeypatch.setattr(release.subprocess, "run", contaminated)
    with pytest.raises(ValueError, match="存档|链接"):
        release.build_release(root)
    assert (external / "save.sqlite3").read_bytes() == b"keep me"


def test_build_rejects_redirected_output_root_before_running_builder(tmp_path, monkeypatch):
    root, _ = project(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    junction(root / "dist" / "releases", outside)
    called = []
    monkeypatch.setattr(release.subprocess, "run", lambda *args, **kwargs: called.append(args))
    with pytest.raises(ValueError, match="项目内"):
        release.build_release(root)
    assert not called and not list(outside.iterdir())


def test_only_declared_project_files_are_added(tmp_path, monkeypatch):
    root, _ = project(tmp_path)
    (root / "terralocal/admin/static/unrelated.txt").write_text("local auxiliary file", "utf-8")
    monkeypatch.setattr(release.subprocess, "run", builder)
    executable = release.build_release(root)
    assert {path.name for path in (executable.parent / "_internal/terralocal/admin/static").iterdir()} == {
        "index.html", "app.js", "app.css",
    }
    assert release.verify_release(executable.parent)["verified"]


def test_executable_version_requires_match_before_publishing(tmp_path, monkeypatch):
    root, _ = project(tmp_path)

    def wrong_version(command, **options):
        if command[1:] == ["--version"]:
            return subprocess.CompletedProcess(command, 0, stdout="9.4.2\n")
        return builder(command, **options)

    monkeypatch.setattr(release.subprocess, "run", wrong_version)
    with pytest.raises(ValueError, match="程序版本"):
        release.build_release(root)
    assert not (root / "dist" / "releases").exists()
    assert len(list((root / "build" / "releases").rglob("TerraLocal.exe"))) == 1


@pytest.mark.parametrize("change", ["same-size-bytes", "extra-file"])
def test_version_probe_must_leave_artifacts_intact(tmp_path, monkeypatch, change):
    root, _ = project(tmp_path)

    def mutate_during_probe(command, *, cwd, **options):
        if command[1:] == ["--version"]:
            if change == "same-size-bytes":
                (cwd / RUNTIME_FILE).write_bytes(b"changed runtime")
            else:
                (cwd / "_internal" / "probe-output.txt").write_text("local probe output", "utf-8")
        return builder(command, cwd=cwd, **options)

    monkeypatch.setattr(release.subprocess, "run", mutate_during_probe)
    with pytest.raises(ValueError, match="发行文件发生变化"):
        release.build_release(root)
    assert not (root / "dist" / "releases").exists()


@pytest.mark.parametrize("unexpected", ["_internal/foreign/original.APK", "_internal/foreign/save.sqlite3-wal",
                                        "_internal/foreign/binding.json", "_internal/terralocal/extra.json",
                                        "README.md"])
def test_unexpected_output_is_rejected_before_program_runs(tmp_path, monkeypatch, unexpected):
    root, _ = project(tmp_path)

    def contaminated(command, **options):
        assert command[1:] != ["--version"]
        result = builder(command, **options)
        artifact = Path(command[command.index("--distpath") + 1]) / "TerraLocal" / unexpected
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text("synthetic unexpected artifact", "utf-8")
        return result

    monkeypatch.setattr(release.subprocess, "run", contaminated)
    with pytest.raises(ValueError, match="凭据|项目数据|路径"):
        release.build_release(root)
    assert not (root / "dist" / "releases").exists()


@pytest.mark.parametrize("change", ["bytes", "unlisted", "missing", "duplicate"])
def test_verify_release_checks_file_set_and_fingerprints(tmp_path, monkeypatch, change):
    root, _ = project(tmp_path)
    monkeypatch.setattr(release.subprocess, "run", builder)
    bundle = release.build_release(root).parent
    if change == "bytes":
        (bundle / RUNTIME_FILE).write_bytes(b"changed runtime")
        reason = "指纹不一致"
    elif change == "unlisted":
        (bundle / "_internal" / "extra.bin").write_bytes(b"unexpected dependency file")
        reason = "文件集合"
    elif change == "missing":
        (bundle / RUNTIME_FILE).unlink()
        reason = "文件集合"
    else:
        manifest = bundle / "build-manifest.json"
        info = json.loads(manifest.read_bytes())
        info["files"].append(info["files"][0])
        manifest.write_text(json.dumps(info), "utf-8")
        reason = "重复路径"
    with pytest.raises(ValueError, match=reason):
        release.verify_release(bundle)


def test_verify_legacy_manifest(tmp_path, monkeypatch):
    root, _ = project(tmp_path)
    monkeypatch.setattr(release.subprocess, "run", builder)
    bundle = release.build_release(root).parent
    manifest = bundle / "build-manifest.json"
    info = json.loads(manifest.read_bytes())
    info.pop("schema_version")
    info["version"] = "0.1.0-development"
    manifest.write_text(json.dumps(info), "utf-8")
    result = release.verify_release(bundle)
    assert result["schema_version"] == 1
    assert result["version"] == "0.1.0-development"
    assert result["files"] == len(info["files"])
