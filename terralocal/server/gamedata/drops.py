"""Offline, versioned local drop policies bound to immutable GameData."""

from __future__ import annotations

import json
import os
import random
import uuid
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from terralocal.server.api.schemas import Command, Identifier
from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.repository import canonical, fingerprint

Mode = Literal["official-like", "guaranteed", "custom", "debug"]
Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
MAX_FILE_BYTES = 32_000_000


class Reward(Command):
    id: Identifier
    count: int = Field(ge=1, le=100_000)
    type: str = Field(min_length=1, max_length=32)


class Outcome(Command):
    weight: int = Field(ge=1, le=1_000_000_000)
    rewards: list[Reward] = Field(max_length=64)


class StageDrops(Command):
    ap_cost: int = Field(ge=0, le=10000)
    sample_count: int = Field(ge=0, le=1_000_000_000)
    interval_start: int = Field(ge=0)
    interval_end: int | None = Field(default=None, ge=0)
    patterns: list[Outcome] = Field(min_length=1, max_length=4096)
    guaranteed_rewards: list[Reward] = Field(max_length=64)
    custom_rewards: list[Reward] = Field(max_length=64)
    debug_rewards: list[Reward] = Field(max_length=64)
    first_pass_rewards: list[Reward] = Field(max_length=64)
    first_complete_rewards: list[Reward] = Field(max_length=64)
    first_pass_basis: str = Field(max_length=160)


class Source(Command):
    name: str = Field(min_length=1, max_length=96)
    url: str = Field(min_length=1, max_length=1024)
    sha256: Hash
    license: str = Field(min_length=1, max_length=96)


class DropCatalog(Command):
    schema_version: Literal[1]
    gamedata_hash: Hash
    policy_version: str = Field(min_length=1, max_length=64)
    mode: Mode
    sources: list[Source] = Field(min_length=1, max_length=16)
    furniture_pool: list[Identifier] = Field(max_length=4096)
    furniture_policy: str = Field(min_length=1, max_length=256)
    stages: dict[Identifier, StageDrops] = Field(min_length=1, max_length=10_000)

    def validate_data(self, data) -> None:
        if self.gamedata_hash != data.manifest["hash"]:
            raise ValueError("掉落规则与所选 GameData 指纹不同")
        if len(self.furniture_pool) != len(set(self.furniture_pool)):
            raise ValueError("家具抽选池包含重复标识")
        for item_id in self.furniture_pool:
            if data.item(item_id)["itemType"] != "FURN":
                raise ValueError("家具抽选池引用了非家具对象")
        for stage_id, row in self.stages.items():
            stage = data.stage(stage_id)
            if row.ap_cost != stage["apCost"]:
                raise ValueError(f"关卡理智费用不同：{stage_id}")
            if sum(outcome.weight for outcome in row.patterns) != row.sample_count:
                raise ValueError(f"掉落组合未覆盖完整样本：{stage_id}")
            if row.interval_end is not None and row.interval_end <= row.interval_start:
                raise ValueError(f"掉落统计时间范围无效：{stage_id}")
            drop_info = stage.get("stageDropInfo") or {}
            displayed = {r["id"] for r in drop_info.get("displayDetailRewards") or []
                         if r["dropType"] not in {"ONCE", "COMPLETE"}}
            known_patterns = set()
            for outcome in row.patterns:
                signature = tuple(sorted((r.id, r.count, r.type) for r in outcome.rewards))
                if signature in known_patterns:
                    raise ValueError(f"掉落组合重复：{stage_id}")
                known_patterns.add(signature)
                if any(r.id != "furni" and r.id not in displayed for r in outcome.rewards):
                    raise ValueError(f"掉落组合与关卡目录不匹配：{stage_id}")
            lists = [row.guaranteed_rewards, row.custom_rewards, row.debug_rewards,
                     row.first_pass_rewards, row.first_complete_rewards]
            for outcome in row.patterns:
                lists.append(outcome.rewards)
            for rewards in lists:
                if len({reward.id for reward in rewards}) != len(rewards):
                    raise ValueError(f"奖励列表包含重复标识：{stage_id}")
                for reward in rewards:
                    if reward.id == "furni":
                        if reward.type != "FURN" or not self.furniture_pool:
                            raise ValueError("随机家具缺少经过校验的抽选池")
                    elif data.item(reward.id)["itemType"] != reward.type:
                        raise ValueError(f"奖励类型不匹配：{stage_id}/{reward.id}")
            if stage["diamondOnceDrop"] and any(reward.id == "4002" for reward in row.first_complete_rewards):
                raise ValueError(f"首次三星源石由关卡定义发放，不能重复声明：{stage_id}")

    def rules(self, data) -> dict:
        self.validate_data(data)
        return {stage_id: {**row.model_dump(), "kind": "versioned-drops-v1", "mode": self.mode,
                           "policy_version": self.policy_version, "gamedata_hash": self.gamedata_hash,
                           "furniture_pool": self.furniture_pool, "furniture_policy": self.furniture_policy}
                for stage_id, row in self.stages.items()}

    def summary(self) -> dict:
        return {"schema_version": self.schema_version, "policy_version": self.policy_version,
                "mode": self.mode, "gamedata_hash": self.gamedata_hash,
                "stages": len(self.stages), "outcomes": sum(len(row.patterns) for row in self.stages.values()),
                "furniture_candidates": len(self.furniture_pool), "sources": [s.model_dump() for s in self.sources],
                "catalog_hash": fingerprint(self.model_dump())}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON 文件包含重复字段")
        result[key] = value
    return result


def read_json(path: Path):
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("掉落规则文件超过大小限制")
    return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_object)


def read_catalog(path: Path, data) -> DropCatalog:
    catalog = DropCatalog.model_validate(read_json(path))
    catalog.validate_data(data)
    return catalog


def select_rewards(rule: dict, seed: int, data) -> list[dict]:
    if rule.get("gamedata_hash") != data.manifest["hash"]:
        raise DomainError("DROP_DATA_CHANGED", "掉落规则与 GameData 不匹配", 503)
    # An explicit version makes the reproducible stream independent of battle
    # telemetry, client timestamps and subsequent requests.
    rng = random.Random(f"{rule['policy_version']}:{seed}")
    mode = rule["mode"]
    if mode == "official-like":
        outcomes = rule["patterns"]
        cursor = rng.randrange(sum(outcome["weight"] for outcome in outcomes))
        for outcome in outcomes:
            cursor -= outcome["weight"]
            if cursor < 0:
                selected = outcome["rewards"]
                break
    elif mode in {"guaranteed", "custom", "debug"}:
        selected = rule[f"{mode}_rewards"]
    else:
        raise DomainError("DROP_MODE_UNSUPPORTED", "掉落模式未实现", 503)
    totals = {}
    for reward in selected:
        if reward["id"] == "furni":
            for _ in range(reward["count"]):
                item_id = rng.choice(rule["furniture_pool"])
                totals[item_id] = totals.get(item_id, 0) + 1
        else:
            totals[reward["id"]] = totals.get(reward["id"], 0) + reward["count"]
    return [{"id": item_id, "count": count, "type": data.item(item_id)["itemType"]}
            for item_id, count in sorted(totals.items())]


def write_catalog(catalog: DropCatalog, folder: Path) -> Path:
    """Preserve immutable policy snapshots before changing the active file."""
    raw = canonical(catalog.model_dump())
    snapshots = folder / "drop-catalogs"
    snapshots.mkdir(parents=True, exist_ok=True)
    saved = snapshots / f"{fingerprint(catalog.model_dump())}.json"
    if saved.exists():
        if saved.read_bytes() != raw:
            raise ValueError("已有掉落规则快照的指纹不匹配")
    else:
        atomic_write(saved, raw)
    target = folder / "drop_rules.json"
    if target.exists():
        previous = read_json(target)
        old_hash = fingerprint(previous)
        previous_raw = canonical(previous)
        old = snapshots / f"{old_hash}.json"
        if old.exists() and old.read_bytes() != previous_raw:
            raise ValueError("原有掉落规则快照的指纹不匹配")
        if not old.exists():
            atomic_write(old, previous_raw)
    atomic_write(target, raw)
    return saved


def atomic_write(path: Path, raw: bytes) -> None:
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
