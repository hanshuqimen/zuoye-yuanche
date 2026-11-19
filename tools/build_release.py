"""Build or verify an isolated portable release."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

EXECUTABLE = "TerraLocal.exe"
MANIFEST = "build-manifest.json"
DOCUMENTS = ("README.md", "STATUS.md", "CHANGELOG.md")
ADMIN_STATIC = Path("terralocal/admin/static")
ADMIN_FILES = ("index.html", "app.js", "app.css")
PACKAGE_FILES = {f"_internal/{(ADMIN_STATIC / name).as_posix()}" for name in ADMIN_FILES}
LOCAL_FOLDERS = {"data", "gamedata", "client", "launcher-client", "profiles", "backups", "logs", "cache", "certs"}
LOCAL_FILES = {"settings.json", "binding.json", "terralocal-login.json", "terralocal-update.json"}
LOCAL_SUFFIXES = {".apk", ".aab", ".apks", ".obb", ".ab", ".vmdk", ".bundle", ".key", ".pfx",
                  ".p12", ".keystore", ".jks", ".log", ".flow"}
SQLITE_NAME = re.compile(r"\.(?:sqlite3?|db)(?:-(?:wal|shm|journal))?$")


def _inside(root: Path, path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root) or resolved == root or resolved != path:
        raise ValueError("构建路径必须位于项目内，不能经目录链接重定向")
    return resolved


def _source_file(root: Path, path: Path) -> Path:
    source = _inside(root, root / path)
    if source.is_symlink() or source.is_junction() or not source.is_file():
        raise ValueError(f"构建缺少普通源文件（{path.as_posix()}）")
    return source


def _artifact_files(bundle: Path) -> dict[str, Path]:
    if bundle.is_symlink() or bundle.is_junction() or not bundle.is_dir() or bundle.resolve() != bundle:
        raise ValueError("发行目录必须为普通目录，不能为链接")
    files = {}
    folders = [bundle]
    while folders:
        current = folders.pop()
        for path in current.iterdir():
            relative = path.relative_to(bundle).as_posix()
            facts = path.lstat()
            if path.is_symlink() or path.is_junction() or not path.resolve().is_relative_to(bundle):
                raise ValueError(f"发行物不能包含链接（{relative}）")
            name = path.name.casefold()
            if stat.S_ISDIR(facts.st_mode):
                if (current == bundle and name != "_internal") or name in LOCAL_FOLDERS:
                    raise ValueError(f"发行物包含存档、资源或未声明目录（{relative}）")
                folders.append(path)
                continue
            if not stat.S_ISREG(facts.st_mode) or facts.st_nlink != 1:
                raise ValueError(f"发行物不能包含特殊文件或硬链接（{relative}）")
            if (name in LOCAL_FILES or name == ".env" or name.startswith(".env.")
                    or path.suffix.casefold() in LOCAL_SUFFIXES or SQLITE_NAME.search(name)):
                raise ValueError(f"发行物包含存档、凭据或资源文件（{relative}）")
            if name.endswith(".pem") and relative != "_internal/certifi/cacert.pem":
                raise ValueError(f"发行物包含未声明的 PEM 文件（{relative}）")
            if relative == "_internal/certifi/cacert.pem" and b"PRIVATE KEY-----" in path.read_bytes():
                raise ValueError("发行物的 CA 文件含有私钥")
            if current == bundle and relative not in (EXECUTABLE, MANIFEST, *DOCUMENTS):
                raise ValueError(f"发行物包含未声明文件（{relative}）")
            if relative.casefold().startswith("_internal/terralocal/") and relative not in PACKAGE_FILES:
                raise ValueError(f"发行物包含未声明的项目数据（{relative}）")
            files[relative] = path
    return files


def _fingerprint(path: Path) -> dict:
    with path.open("rb") as stream:
        return {"bytes": os.fstat(stream.fileno()).st_size, "sha256": hashlib.file_digest(stream, "sha256").hexdigest()}


def _inventory(files: dict[str, Path]) -> dict[str, dict]:
    required = {EXECUTABLE, *DOCUMENTS, *PACKAGE_FILES}
    if not required <= files.keys() or not files[EXECUTABLE].stat().st_size:
        raise ValueError("发行物缺少有效的程序、项目文档或管理页面文件")
    return {name: _fingerprint(path) for name, path in sorted(files.items()) if name != MANIFEST}


def verify_release(bundle: Path) -> dict:
    """Check an unpacked release against its manifest without starting it."""
    bundle = Path(os.path.abspath(bundle))
    files = _artifact_files(bundle)
    if MANIFEST not in files:
        raise ValueError("发行物缺少构建清单")
    manifest = json.loads(files[MANIFEST].read_bytes())
    schema = manifest.get("schema_version", 1) if isinstance(manifest, dict) else None
    if type(schema) is not int or schema not in (1, 2):
        raise ValueError("发行清单版本无效")
    if any(not isinstance(manifest.get(name), str) or not manifest[name] for name in ("build_id", "version")):
        raise ValueError("发行清单缺少构建编号或程序版本")
    rows = manifest.get("files")
    if not isinstance(rows, list) or any(not isinstance(row, dict) or not isinstance(row.get("path"), str)
                                        for row in rows):
        raise ValueError("发行清单的文件记录格式无效")
    expected = {row["path"]: row for row in rows}
    if len(expected) != len(rows):
        raise ValueError("发行清单包含重复路径")
    actual = _inventory(files)
    if expected.keys() != actual.keys():
        raise ValueError("发行清单与实际文件集合不一致")
    for name, facts in actual.items():
        if expected[name] != {"path": name, **facts}:
            raise ValueError(f"发行文件大小或指纹不一致（{name}）")
    return {"verified": True, "build_id": manifest.get("build_id"), "version": manifest.get("version"),
            "schema_version": schema, "files": len(actual)}


def build_release(root: Path, *, clean: bool = False) -> Path:
    root = root.resolve(strict=True)
    metadata = tomllib.loads(_source_file(root, Path("pyproject.toml")).read_text(encoding="utf-8"))
    project = metadata.get("project")
    version = project.get("version") if isinstance(project, dict) else None
    if not isinstance(version, str) or not version or version.split() != [version]:
        raise ValueError("项目版本字段无效")
    entry = _source_file(root, Path("terralocal/__main__.py"))
    documents = [_source_file(root, Path(name)) for name in DOCUMENTS]
    assets = [_source_file(root, ADMIN_STATIC / name) for name in ADMIN_FILES]
    # PyInstaller clears its COLLECT destination even without --clean. Never
    # direct COLLECT at an existing installation, including its portable data.
    build_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ") + "-" + uuid4().hex[:8]
    work = _inside(root, root / "build" / "releases" / build_id)
    output = _inside(root, root / "dist" / "releases" / build_id)
    work.mkdir(parents=True, exist_ok=False)
    staged = work / "collected"
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--onedir", "--console",
               "--name", "TerraLocal", "--contents-directory", "_internal", "--distpath", str(staged),
               "--workpath", str(work / "pyinstaller"), "--specpath", str(work),
               "--exclude-module", "frida", "--exclude-module", "UnityPy",
               "--exclude-module", "pytest", "--exclude-module", "tkinter.test"]
    for asset in assets:
        command.extend(("--add-data", str(asset) + os.pathsep + ADMIN_STATIC.as_posix()))
    if clean:
        command.append("--clean")
    command.append(str(entry))
    subprocess.run(command, cwd=root, check=True)
    bundle = staged / "TerraLocal"
    executable = bundle / EXECUTABLE
    files = _artifact_files(bundle)
    if files.keys() & {MANIFEST, *DOCUMENTS}:
        raise ValueError("打包结果占用了发行清单或文档路径")
    for document in documents:
        with document.open("rb") as source, (bundle / document.name).open("xb") as target:
            shutil.copyfileobj(source, target)
    inventory = _inventory(_artifact_files(bundle))
    for asset in assets:
        relative = f"_internal/{(ADMIN_STATIC / asset.name).as_posix()}"
        if inventory[relative] != _fingerprint(asset):
            raise ValueError(f"管理页面文件与源码不一致（{asset.name}）")
    probe = subprocess.run([str(executable), "--version"], cwd=bundle, check=True, capture_output=True,
                           text=True, encoding="utf-8", timeout=30)
    if probe.stdout.strip() != version:
        raise ValueError("程序版本与项目版本不一致")
    if inventory != _inventory(_artifact_files(bundle)):
        raise ValueError("版本检查期间发行文件发生变化")
    manifest = {"schema_version": 2, "version": version, "build_id": build_id, "client_verified": False,
                "official_apk_included": False, "official_resources_included": False,
                "files": [{"path": name, **facts} for name, facts in inventory.items()]}
    with (bundle / MANIFEST).open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    _inside(root, output).mkdir(parents=True, exist_ok=False)
    destination = _inside(root, output / "TerraLocal")
    _inside(root, bundle).rename(destination)
    return destination / EXECUTABLE


def main() -> int:
    parser = argparse.ArgumentParser(description="构建独立发行目录或核对已解压发行物")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--clean", action="store_true", help="清理打包器缓存，不删除已有发行目录")
    mode.add_argument("--verify", type=Path, metavar="DIR", help="只读核对发行目录的成员和 SHA-256")
    options = parser.parse_args()
    try:
        if options.verify is not None:
            print(json.dumps(verify_release(options.verify), ensure_ascii=False))
        else:
            executable = build_release(Path(__file__).resolve().parents[1], clean=options.clean)
            print(executable)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"TerraLocal {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
