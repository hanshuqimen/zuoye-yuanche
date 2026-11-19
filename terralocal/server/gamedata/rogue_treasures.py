"""Explicit preselected WISH outcomes; no inferred pool, unlock or frequency.

The trusted provider supplies the menu and eligibility, resolves each possible
choice before publishing it, and persists this source with the map. This pure
compiler neither activates a node nor grants a relic. A client sends choice
only; item IDs are never accepted from its scene-selection request.
"""

import json
from dataclasses import dataclass, replace
from types import MappingProxyType

from terralocal.server.gamedata.repository import canonical, fingerprint
from terralocal.server.gamedata.rogue_battle_loot import RelicGroups, compile_groups
from terralocal.server.gamedata.rogue_capacity_relics import supported as capacity_supported
from terralocal.server.gamedata.rogue_events import LEAVE_DIGEST, Branch, Delta, EventSpec, Frame
from terralocal.server.gamedata.rogue_gold_relics import supported as gold_supported

POLICY = "rogue1-explicit-treasure-outcomes-v1"
VARIANTS = MappingProxyType({
    "history": ("scene_treasure1_enter", "scene_treasure1_1", ("choice_treasure1_1",)),
    "fate": ("scene_treasure2_enter", "scene_treasure2_1", ("choice_treasure2_1", "choice_treasure2_2")),
})
PROGRAMS = frozenset("rogue1-treasure-" + key + "-v1" for key in VARIANTS)
CHOICE_HASHES = MappingProxyType({
    "choice_treasure1_1": "c800220ce837e5e8b1a74cf83dd75b18b7505009086f5402e173b515cdabc21c",
    "choice_treasure2_1": "b3f8a247ebd0657c6bbc6c3958c3554c1989c334a8ec955625aeed9df9504b3f",
    "choice_treasure2_2": "caebb6a8b9c0cbdcedc6ce4de32396750db932bb2176162fab2274a2e1505e67",
})
SCENE_HASHES = MappingProxyType({
    "scene_treasure1_1": "161066cb1ea666e434937fe4a2cc6ec97056b431f35fb351e901b2dbe4b1a322",
    "scene_treasure1_enter": "0753db783875f3d8b4826b1c1a03bf984d4a3d55552d5c1e14733081c2ba597e",
    "scene_treasure2_1": "a7dd8f8245267b49b40eccc690b8add80984810bb40fa0776b8b186acaeb4f5c",
    "scene_treasure2_enter": "4ae7e5f96bd9d33c92284ad18bb8049d2797d862acd1ad6f6aa83391bbf72729",
})


def invalid():
    return ValueError("馈赠必须有匹配场景、明确菜单、完整效果和可信资格的保存方案")


@dataclass(frozen=True)
class Treasure:
    program: object
    source: bytes
    grants: object
    reservations: frozenset[str]


def compile_treasure(data, value, *, at):
    if (type(value) is not dict or set(value) != {"schema", "policy", "variant", "rewards", "eligibility", "evidence"}
            or type(value["schema"]) is not int or value["schema"] != 1 or value["policy"] != POLICY
            or type(value["variant"]) is not str or value["variant"] not in VARIANTS
            or type(value["rewards"]) is not list or not 1 <= len(value["rewards"]) <= 2
            or type(value["eligibility"]) is not list or not 1 <= len(value["eligibility"]) <= 512
            or any(type(k) is not str for k in value["eligibility"])
            or len(set(value["eligibility"])) != len(value["eligibility"])
            or type(value["evidence"]) is not str or not 1 <= len(value["evidence"]) <= 1024
            or type(at) is not int or not 0 <= at < 2**63):
        raise invalid()
    source = canonical(value)
    if len(source) > 16384:
        raise invalid()
    entry, result, allowed = VARIANTS[value["variant"]]
    detail = data.table("roguelike_topic_table")["details"]["rogue_1"]
    data.rogue_topics.topic("rogue_1", at=at)
    for key in (entry, result):
        if fingerprint(detail["choiceScenes"].get(key)) != SCENE_HASHES[key]:
            raise invalid()
    grants, branches, proofs = {}, [], []
    for reward in value["rewards"]:
        if (type(reward) is not dict or set(reward) != {"choice", "item"}
                or type(reward["choice"]) is not str or reward["choice"] not in allowed
                or reward["choice"] in grants or type(reward["item"]) is not str):
            raise invalid()
        choice, item = reward["choice"], reward["item"]
        row = detail["choices"].get(choice)
        if (fingerprint(row) != CHOICE_HASHES[choice] or row["type"] != "TRADE"
                or row["nextSceneId"] != result or row["displayData"]["type"] != "NORMAL"
                or row["displayData"]["itemId"] is not None):
            raise invalid()
        # A preselected outcome is distinct from an eligible candidate pool.
        # Reuse the complete effect proof, not the battle encounter policy.
        _, proof = compile_groups(data, RelicGroups(((item,),), frozenset(value["eligibility"]), value["evidence"]), at=at)
        ref = data.rogue_relic_archive.entries[item]
        if ref.special:
            raise invalid()  # WISH is not authority for limited/event-only relics.
        delta = Delta(gold=data.rogue_gold_relics.require(item) if gold_supported(data, item) else 0,
                      squad_capacity=data.rogue_capacity_relics.require(item) if capacity_supported(data, item) else 0)
        grants[choice] = item
        branches.append(Branch(choice, CHOICE_HASHES[choice], delta))
        proofs.append([choice, item, proof])
    # Fate menu membership/order is explicitly supplied. This does not assert
    # which menu combination or high-rarity outcome the official server draws.
    program = data.rogue_scenes.compile(EventSpec("rogue1-treasure-" + value["variant"] + "-v1", entry,
        (Frame(entry, tuple(branches)), Frame(result, (Branch("choice_leave", LEAVE_DIGEST, Delta()),))),
        value["evidence"]))
    if program.choices["choice_leave"].target is not None:
        raise invalid()
    digest = fingerprint({"policy": POLICY, "data": data.manifest["hash"], "at": at,
        "source": json.loads(source), "graph": program.digest, "proofs": proofs,
        "scenes": {k: SCENE_HASHES[k] for k in (entry, result)}})
    return Treasure(replace(program, digest=digest), source, MappingProxyType(grants), frozenset(grants.values()))
