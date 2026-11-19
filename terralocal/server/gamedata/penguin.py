"""Compile downloaded public Penguin Statistics data without network access.

Joint observed patterns retain correlations. Source sample weights are never
renormalized from an incomplete subset. Furniture identity and missing first
pass quantities use explicitly labelled local policies rather than asserting
official equivalence.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path

from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.drops import DropCatalog, read_json
from terralocal.server.gamedata.repository import fingerprint

PATTERN_URL = "https://penguin-stats.io/PenguinStats/api/v2/result/pattern?server=CN&show_all_patterns=true"
STAGE_URL = "https://penguin-stats.io/PenguinStats/api/v2/stages"
LOCAL_FIRST_PASS = "GameData ONCE display entries; local quantity=1 where the table omits counts"
FURNITURE_POLICY = "Local uniform choice from GameData furniture labelled lucky stage drops; official pool weights unknown"


def ordinary_stage(stage, protection) -> bool:
    return (stage.get("stageType") == "MAIN" and stage.get("difficulty") == "NORMAL"
            and stage.get("diffGroup") == "NONE" and not stage.get("isStoryOnly")
            and not stage.get("isPredefined") and not stage.get("isHardPredefined")
            and not stage.get("isStagePatch") and stage.get("apCost", -1) >= 0
            and stage.get("apProtectTimes", 0) == 0 and stage.get("zoneId") not in protection)


def reward(data, item_id, count):
    if type(count) is not int or not 1 <= count <= 100_000:
        raise ValueError("物品数量超出范围")
    return {"id": item_id, "count": count,
            "type": "FURN" if item_id == "furni" else data.item(item_id)["itemType"]}


def counted_rewards(data, source):
    return [reward(data, entry["id"], entry["count"]) for entry in source]


def first_rewards(data, definition):
    info = definition.get("stageDropInfo") or {}
    declared = info.get("firstPassRewards")
    if declared is not None:
        first_pass = counted_rewards(data, declared)
        basis = "Explicit GameData firstPassRewards counts"
    else:
        first_pass = [reward(data, entry["id"], 1) for entry in info.get("displayRewards") or []
                      if entry["dropType"] == "ONCE"]
        basis = LOCAL_FIRST_PASS
    declared_complete = info.get("firstCompleteRewards")
    if declared_complete is not None:
        first_complete = counted_rewards(data, declared_complete)
    else:
        first_complete = [reward(data, entry["id"], 1) for entry in info.get("displayRewards") or []
                          if entry["dropType"] == "COMPLETE" and entry["id"] != "4002"]
        if first_complete:
            basis += "; COMPLETE display quantity=1"
    # The domain's GameData diamondOnceDrop already grants first three-star OP.
    if definition.get("diamondOnceDrop", 0):
        first_complete = [entry for entry in first_complete if entry["id"] != "4002"]
    # Character awards use Context.rewards/acquire_standard, shared with the
    # predefined training path. Do not exclude an entire ordinary stage just
    # because its one-time reward includes an operator.
    for entry in first_pass + first_complete:
        if entry["type"] == "CHAR" and data.character(entry["id"]).get("isNotObtainable"):
            raise ValueError("首次奖励引用不可获取干员")
    return first_pass, first_complete, basis


def stage_patterns(data, definition, public, records):
    # Penguin labels mainline side stages SUB; the frozen client keeps their
    # stageType MAIN and distinguishes them with appearanceStyle SUB. Require
    # that explicit pair, rather than admitting every SUB/public type mismatch.
    source_types = {"MAIN", "SUB"} if definition.get("appearanceStyle") == "SUB" else {"MAIN"}
    if public.get("apCost") != definition["apCost"] or public.get("stageType") not in source_types:
        raise ValueError("来源关卡类型或理智费用与 GameData 不匹配")
    if public.get("existence", {}).get("CN", {}).get("exist") is not True:
        raise ValueError("来源没有开放的国服关卡")
    active = [entry for entry in records if entry.get("end") is None]
    if not active:
        raise ValueError("没有开放时间范围的完整组合样本")
    starts = {entry.get("start") for entry in active}
    samples = {entry.get("times") for entry in active}
    if len(starts) != 1 or len(samples) != 1:
        raise ValueError("组合统计混用了不同时间范围或样本数")
    start, count = starts.pop(), samples.pop()
    if type(start) is not int or start < 0 or type(count) is not int or count < 1:
        raise ValueError("组合统计时间或样本数无效")
    displayed = {entry["id"] for entry in (definition.get("stageDropInfo") or {}).get(
        "displayDetailRewards") or [] if entry["dropType"] not in {"ONCE", "COMPLETE"}}
    bounds = defaultdict(lambda: [0, 0])
    for entry in public.get("dropInfos") or []:
        item_id = entry.get("itemId")
        if item_id is None:
            continue  # Group-size bounds are not item-quantity bounds.
        lower, upper = entry["bounds"]["lower"], entry["bounds"]["upper"]
        if type(lower) is not int or type(upper) is not int or not 0 <= lower <= upper <= 100_000:
            raise ValueError("来源数量范围无效")
        bounds[item_id][0] += lower
        bounds[item_id][1] += upper
    outcomes = []
    signatures = set()
    for entry in active:
        weight = entry["quantity"]
        if type(weight) is not int or weight < 1:
            raise ValueError("组合样本权重必须为正整数")
        amounts = {}
        for drop in entry["pattern"]["drops"]:
            item_id, quantity = drop["itemId"], drop["quantity"]
            if item_id in amounts or item_id not in bounds:
                raise ValueError("组合物品重复或不在来源目录")
            if item_id != "furni" and item_id not in displayed:
                raise ValueError("组合物品与匹配 GameData 的关卡目录不同")
            if type(quantity) is not int or not 1 <= quantity <= bounds[item_id][1]:
                raise ValueError("组合数量超出来源范围")
            amounts[item_id] = quantity
        if any(amounts.get(item_id, 0) < interval[0] for item_id, interval in bounds.items()):
            raise ValueError("组合缺少来源定义的必掉物品")
        signature = tuple(sorted(amounts.items()))
        if signature in signatures:
            raise ValueError("重复的组合样本")
        signatures.add(signature)
        outcomes.append({"weight": weight, "rewards": [reward(data, k, v) for k, v in signature]})
    if sum(row["weight"] for row in outcomes) != count:
        raise ValueError("组合统计未覆盖全部样本；请使用 show_all_patterns=true")
    # Sorting also makes reordered downloads yield the same local catalog.
    outcomes.sort(key=lambda row: fingerprint(row["rewards"]))
    all_ids = sorted({r["id"] for row in outcomes for r in row["rewards"]})
    quantities = [{r["id"]: r["count"] for r in row["rewards"]} for row in outcomes]
    minima = {k: min(row.get(k, 0) for row in quantities) for k in all_ids}
    maxima = {k: max(row.get(k, 0) for row in quantities) for k in all_ids}
    guaranteed = [reward(data, k, v) for k, v in minima.items() if v]
    debug = [reward(data, k, v) for k, v in maxima.items() if v]
    first_pass, first_complete, basis = first_rewards(data, definition)
    return {"ap_cost": definition["apCost"], "sample_count": count, "interval_start": start,
            "interval_end": None, "patterns": outcomes, "guaranteed_rewards": guaranteed,
            "custom_rewards": guaranteed, "debug_rewards": debug,
            "first_pass_rewards": first_pass, "first_complete_rewards": first_complete,
            "first_pass_basis": basis}


def compile_penguin(patterns_path: Path, stages_path: Path, data, *, mode="official-like"):
    patterns, stages = read_json(patterns_path), read_json(stages_path)
    if not isinstance(patterns, dict) or not isinstance(patterns.get("pattern_matrix"), list):
        raise ValueError("组合文件必须含 pattern_matrix 列表")
    if not isinstance(stages, list):
        raise ValueError("关卡文件必须为列表")
    grouped = defaultdict(list)
    for row in patterns["pattern_matrix"]:
        if not isinstance(row, dict) or not isinstance(row.get("stageId"), str):
            raise ValueError("组合条目缺少关卡标识")
        grouped[row["stageId"]].append(row)
    by_stage = {}
    for row in stages:
        if not isinstance(row, dict) or not isinstance(row.get("stageId"), str) or row["stageId"] in by_stage:
            raise ValueError("来源关卡标识缺失或重复")
        by_stage[row["stageId"]] = row
    source_hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in (patterns_path, stages_path)]
    protection = data.table("stage_table").get("apProtectZoneInfo", {})
    imported, excluded = {}, {}
    for stage_id, definition in data.stages.items():
        if not ordinary_stage(definition, protection):
            continue
        try:
            if stage_id not in by_stage:
                raise ValueError("来源关卡目录缺失")
            imported[stage_id] = stage_patterns(data, definition, by_stage[stage_id], grouped[stage_id])
        except (ValueError, KeyError, TypeError, DomainError) as exc:
            excluded[stage_id] = exc.message if isinstance(exc, DomainError) else str(exc)
    if not imported:
        raise ValueError("没有与 GameData 匹配的完整普通关卡组合")
    furniture = sorted(item_id for item_id, row in data.furnitures.items()
                       if row.get("obtainApproach") in {"家具商店购买，部分关卡幸运掉落", "部分关卡幸运掉落"})
    raw = {"schema_version": 1, "gamedata_hash": data.manifest["hash"],
           "policy_version": f"penguin-cn-joint-v1-{source_hashes[0][:12]}", "mode": mode,
           "sources": [{"name": "Penguin Statistics CN " + name, "url": url,
                        "sha256": digest, "license": "CC-BY-NC-4.0"}
                       for name, url, digest in zip(("joint patterns", "stage bounds"),
                                                    (PATTERN_URL, STAGE_URL), source_hashes, strict=True)],
           "furniture_pool": furniture, "furniture_policy": FURNITURE_POLICY, "stages": imported}
    catalog = DropCatalog.model_validate(raw)
    catalog.validate_data(data)
    reasons = defaultdict(int)
    for reason in excluded.values():
        reasons[reason] += 1
    return catalog, {"supported_stages": len(imported), "excluded_stages": excluded,
                     "excluded_reasons": dict(reasons), "policy_notes": [LOCAL_FIRST_PASS, FURNITURE_POLICY,
                         "Observed joint patterns are empirical; no claim of official probability equivalence",
                         "Guaranteed/custom defaults use observed per-item minima; debug uses maxima"]}
