"""Prepare a separate, content-addressed Crisis V2 GameData package.

Accepts the info object only, never a historical player delta or a response
envelope. This local preparation does not select a profile or open a save.
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def prepare(base_directory, shared_file, version_file, info_files, cache, source, *, dry_run=False):
    from terralocal.server.gamedata import GameData, import_data
    from terralocal.server.gamedata.crisis_v2 import CLIENT_ELF_SHA256
    from terralocal.server.gamedata.crisis_v2_catalog import CALENDAR, INFO_FIELDS, SERVER_TABLE
    from terralocal.server.gamedata.repository import canonical, fingerprint, validate_tables

    cache = Path(cache).resolve()
    if not cache.is_relative_to(ROOT):
        raise ValueError("研究准备的输出缓存必须位于本项目内")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("必须明确记录信息源")
    base = GameData(Path(base_directory))
    base.verify()
    version = Path(version_file).read_text(encoding="utf-8-sig").strip()
    if version != base.manifest["version"]:
        raise ValueError("共享表版本记录与基础GameData不匹配")
    shared = json.loads(Path(shared_file).read_bytes())
    tables = {name: base.table(name) for name in base.manifest["tables"]}
    if "crisis_v2_table" in tables and fingerprint(shared) != fingerprint(tables["crisis_v2_table"]):
        raise ValueError("基础数据已有另一份共享表；请从原始基线建立独立配置")
    tables["crisis_v2_table"] = shared
    server = {"schema": 1, "data_version": version, "client_elf_sha256": CLIENT_ELF_SHA256,
              "calendar_policy": CALENDAR, "seasons": {}}
    if SERVER_TABLE in tables:
        server = json.loads(canonical(tables[SERVER_TABLE]))
    for path in info_files:
        info = json.loads(Path(path).read_bytes())
        if type(info) is not dict or set(info) != INFO_FIELDS:
            raise ValueError("仅接纳info对象；响应包装、玩家delta和额外字段不能作为信息源")
        key = info["seasonId"]
        if type(key) is not str or not key:
            raise ValueError("信息源缺少赛季标识")
        if key in server["seasons"]:
            if fingerprint(server["seasons"][key]["info"]) != fingerprint(info):
                raise ValueError("同一赛季已有不同信息源；请保留原配置")
        else:
            server["seasons"][key] = {"info": info, "source": source}
    tables[SERVER_TABLE] = server
    validate_tables(tables, version=version)
    hashes = {name: fingerprint(table) for name, table in tables.items()}
    digest = fingerprint({"adapter": "cn-json-v1", "version": version, "tables": hashes})
    client_verified = False
    if not dry_run:
        cache.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".crisis-info-", dir=cache.parent) as temporary:
            folder = Path(temporary)
            for name, table in tables.items():
                (folder / (name + ".json")).write_bytes(canonical(table))
            (folder / "data_version.txt").write_text(version, encoding="utf8")
            manifest = import_data(folder, cache, source=source)
            if manifest["hash"] != digest:
                raise ValueError("准备后的数据指纹不一致")
            client_verified = manifest["client_verified"]
    return {"gamedata_hash": digest, "directory": str(cache / digest), "tables": len(tables),
            "seasons": sorted(server["seasons"]), "version": version, "dry_run": dry_run,
            "activated": False, "client_verified": client_verified, "native_verification_performed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, type=Path, help="已验证的基础GameData哈希目录")
    parser.add_argument("--shared", required=True, type=Path, help="匹配版本的crisis_v2_table.json")
    parser.add_argument("--version-file", required=True, type=Path, help="共享表来源的data_version.txt")
    parser.add_argument("--info", required=True, type=Path, action="append", help="独立info对象，可重复指定")
    parser.add_argument("--cache", required=True, type=Path, help="项目内输出缓存，不切换运行配置")
    parser.add_argument("--source", required=True, help="固定来源、版本或本地数据说明")
    parser.add_argument("--dry-run", action="store_true", help="校验并计算指纹，不写入数据")
    args = parser.parse_args()
    try:
        result = prepare(args.base, args.shared, args.version_file, args.info, args.cache, args.source,
                         dry_run=args.dry_run)
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(2, str(exc) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
