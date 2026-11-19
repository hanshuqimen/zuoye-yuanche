"""Explicit battle relic groups; no inferred encounter pool or drop weights.

Eligibility is supplied by a trusted server driver with recorded evidence.
The compiler checks complete supported effects and freezes bounded choices.
Shop compilation is reused only as an effect-definition validator; its zero
proof price establishes neither a real merchant price nor drop eligibility.
"""

from dataclasses import dataclass

from terralocal.server.gamedata.repository import canonical, fingerprint
from terralocal.server.gamedata.rogue_battle_effects import require_open, supported
from terralocal.server.gamedata.rogue_capacity_relics import supported as capacity_supported
from terralocal.server.gamedata.rogue_currency_relics import supported as currency_supported
from terralocal.server.gamedata.rogue_gold_relics import supported as gold_supported
from terralocal.server.gamedata.rogue_life_relics import supported as life_supported
from terralocal.server.gamedata.rogue_resource_relics import supported as resource_supported
from terralocal.server.gamedata.rogue_shops import Offer, compile_shop

POLICY = "rogue1-explicit-battle-relic-groups-v1"
RESOURCE_POLICY = "rogue1-explicit-battle-resource-relic-groups-v2"
CAPSULE_POLICY = "rogue1-explicit-battle-capsule-groups-v3"
BASE_POLICY = "rogue1-explicit-base-battle-rewards-v4"
POLICIES = frozenset({POLICY, RESOURCE_POLICY, CAPSULE_POLICY, BASE_POLICY})
MAX_GROUPS, MAX_CHOICES, MAX_ITEMS = 8, 8, 32  # Local admission budgets.


@dataclass(frozen=True)
class RelicGroups:
    groups: tuple[tuple[str, ...], ...]
    eligibility: frozenset[str]
    evidence: str
    capsule: str | None = None
    base_only: bool = False


def compile_groups(data, spec, *, at):
    if (type(spec) is not RelicGroups or type(spec.groups) is not tuple
            or type(spec.base_only) is not bool
            or not 0 <= len(spec.groups) <= MAX_GROUPS or not spec.groups and spec.capsule is None and not spec.base_only
            or spec.base_only and (spec.groups != () or spec.eligibility != frozenset() or spec.capsule is not None)
            or type(spec.eligibility) is not frozenset or not 0 <= len(spec.eligibility) <= 512
            or any(type(key) is not str for key in spec.eligibility)
            or type(spec.evidence) is not str or not 1 <= len(spec.evidence) <= 1024
            or type(at) is not int or not 0 <= at < 2**63):
        raise ValueError("战斗收藏品奖励须有明确的有界方案、资格来源和时间")
    seen, offers, resource_effect = set(), [], False
    data.rogue_topics.topic("rogue_1", at=at)
    for i, group in enumerate(spec.groups):
        if type(group) is not tuple or not 1 <= len(group) <= MAX_CHOICES:
            raise ValueError("奖励组须明确给出有限的候选")
        for sub, key in enumerate(group):
            if type(key) is not str or key in seen or key not in spec.eligibility:
                raise ValueError("奖励候选重复或缺少明确资格")
            seen.add(key)
            if key in data.rogue_recruit_costs.modifiers:
                pass  # Explicit eligibility, not a guessed unlock-text rule.
            elif supported(data, key):
                require_open(data, key, at)
            elif capacity_supported(data, key):
                data.rogue_capacity_relics.require(key)
            elif (gold_supported(data, key) or resource_supported(data, key) or currency_supported(data, key)
                  or life_supported(data, key)):
                resource_effect = True
            else:
                raise ValueError("此收藏品的战斗获得效果尚未完整接通")
            offers.append(Offer(f"g{i}s{sub}", key, 0, relic_layer=0))
    if len(offers) > MAX_ITEMS:
        raise ValueError("战斗奖励候选总量超过本地预算")
    proof = compile_shop(data, "battle-loot-effect-proof", tuple(offers),
        evidence="Complete effect definitions only; no price, merchant or natural drop eligibility claim") if offers else None
    value = {"schema": 1, "policy": RESOURCE_POLICY if resource_effect else POLICY, "groups": [list(g) for g in spec.groups],
             "eligibility": sorted(seen), "evidence": spec.evidence, "at": at, "effects": proof.digest if proof else None}
    if spec.base_only:
        detail = data.table("roguelike_topic_table")["details"]["rogue_1"]
        gold = detail["gameConst"]["goldItemId"]
        item = detail["items"].get(gold)
        if not isinstance(item, dict) or item.get("type") != "GOLD" or item.get("id") != gold:
            raise ValueError("基础战斗奖励缺少匹配的主题源石锭引用")
        value |= {"policy": BASE_POLICY, "base_only": True,
                  "effects": fingerprint({"data": data.manifest["hash"], "at": at, "gold": item,
                                          "kind": "BATTLE_NORMAL", "extra_rewards": []})}
    if spec.capsule is not None:
        from terralocal.server.gamedata.rogue_capsules import require

        definition = require(data, spec.capsule, at=at)
        value |= {"policy": CAPSULE_POLICY, "capsule": {"id": definition.id, "rule": definition.digest}}
    return value, fingerprint(value)


def admit_groups(data, value):
    if (type(value) is not dict or set(value) != ({"schema", "policy", "groups", "eligibility", "evidence", "at", "effects"}
            | ({"capsule"} if value.get("policy") == CAPSULE_POLICY else {"base_only"}
               if value.get("policy") == BASE_POLICY else set()))
            or type(value["schema"]) is not int or value["schema"] != 1 or value["policy"] not in POLICIES
            or type(value["groups"]) is not list or any(type(g) is not list for g in value["groups"])
            or type(value["eligibility"]) is not list or any(type(k) is not str for k in value["eligibility"])
            or len(set(value["eligibility"])) != len(value["eligibility"])):
        raise ValueError("战斗收藏品方案保存结构不匹配")
    capsule = value.get("capsule")
    if capsule is not None and (type(capsule) is not dict or set(capsule) != {"id", "rule"}):
        raise ValueError("剧目奖励定义保存结构不匹配")
    compiled, digest = compile_groups(data, RelicGroups(tuple(tuple(g) for g in value["groups"]),
        frozenset(value["eligibility"]), value["evidence"], None if capsule is None else capsule["id"],
        value.get("base_only", False)), at=value["at"])
    if canonical(compiled) != canonical(value):
        raise ValueError("战斗收藏品方案或完整效果发生变化")
    return compiled, digest


def loot(value):
    result = [{"kind": "RELIC_CHOICE", "items": [
        {"id": key, "count": 1, "sub": sub} for sub, key in enumerate(group)]}
        for group in value["groups"]]
    if "capsule" in value:
        result.append({"kind": "CAPSULE", "id": value["capsule"]["id"], "count": 1})
    return result


def selected(item, sub):
    if (type(item) is not dict or item.get("kind") != "RELIC_CHOICE" or type(sub) is not int
            or not 0 <= sub < len(item["items"])):
        raise ValueError("收藏品选择不属于此奖励组")
    return item["items"][sub]["id"]


def gold_after_relic(data, key, balance):
    """One immediate reward, shared by transaction and immutable claim replay.

    Resource-layer relics keep their base inventory layer; their native battle
    consumer calculates its current gold-dependent layer separately.
    """
    if gold_supported(data, key):
        amount = data.rogue_gold_relics.require(key)
    elif currency_supported(data, key):
        amount = data.rogue_currency_relics.require(key).gold
    else:
        return balance
    if type(balance) is not int or not 0 <= balance < 2**31 or balance + amount >= 2**31:
        raise ValueError("立即源石锭奖励超出客户端整数范围")
    return balance + amount
