"""Validate public gacha-detail data and freeze selected native-compatible pools.

No login, official authentication or runtime network dependency. The supplied
public JSON stays a local research artifact, with its SHA-256 in the receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from terralocal.config import load_settings  # noqa: E402
from terralocal.server.gamedata import GameData  # noqa: E402
from terralocal.server.gamedata.headhunting_rules import HeadHuntingRules  # noqa: E402
from terralocal.server.gamedata.repository import canonical, fingerprint  # noqa: E402


def freeze(source: Path, data: GameData, pools: list[str]) -> HeadHuntingRules:
    if source.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("寻访来源超过 16 MiB")
    body = source.read_bytes()
    rows = json.loads(body)["gachaPoolClient"]
    ids = [r["gachaPoolId"] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("寻访来源包含重复卡池")
    definitions = {r["gachaPoolId"]: r for r in data.table("gacha_table")["gachaPoolClient"]}
    details = {r["gachaPoolId"]: r["gachaPoolDetail"] for r in rows}
    output = {}
    for pool_id in sorted(set(pools)):
        if pool_id not in details or pool_id not in definitions:
            raise ValueError("来源或 GameData 不包含所选卡池")
        detail = details[pool_id]
        # No delta, credentials or unrelated account data belong in the catalog.
        output[pool_id] = {"rule_type": definitions[pool_id]["gachaRuleType"],
                           "detail": {k: detail[k] for k in ("detailInfo", "gachaObjGroupType", "hasRateUp")}}
    rules = HeadHuntingRules.model_validate({"schema_version": 1, "gamedata_hash": data.manifest["hash"],
        "source_url": "https://weedy.prts.wiki/gacha_table.json", "source_sha256": hashlib.sha256(body).hexdigest(),
        "pools": output})
    rules.validate_data(data)
    return rules


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--pool", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    settings = load_settings(args.data_dir)
    if not settings.gamedata_hash:
        raise ValueError("请先选择匹配的 GameData")
    data = GameData(settings.data_dir / "cache" / settings.gamedata_hash)
    data.verify()
    rules = freeze(args.source, data, args.pool)
    content = canonical(rules.model_dump())
    target = args.output.resolve()
    if target.exists():
        if json.loads(target.read_bytes()) != rules.model_dump():
            raise ValueError("保留原快照，请选择新的输出文件")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        with temporary.open("xb") as stream:
            stream.write(content)
        os.replace(temporary, target)
    receipt = {"gamedata_hash": data.manifest["hash"], "catalog_hash": fingerprint(rules.model_dump()),
               "source_sha256": rules.source_sha256,
               "pools": {k: {"rule_type": v["rule_type"],
                    "characters": {r: len(ids) for r, ids in v["characters"].items()}}
                         for k, v in rules.validate_data(data).items()}}
    target.with_suffix(".receipt.json").write_bytes(canonical(receipt))
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    main()
