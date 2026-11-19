"""Frozen base "暴殄天物" plans for the first-theme recreation node."""

from dataclasses import dataclass, replace
from types import MappingProxyType

from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.gamedata.rogue_battle_loot import RelicGroups, compile_groups
from terralocal.server.gamedata.rogue_capacity_relics import supported as capacity_supported
from terralocal.server.gamedata.rogue_events import (
    LEAVE_DIGEST,
    Branch,
    Delta,
    EventProgram,
    EventSpec,
    Frame,
)
from terralocal.server.gamedata.rogue_gold_relics import supported as gold_supported

PROGRAM = "rogue1-recreation-cellar-v1"
ENTRY = "scene_ent3_enter"
GOLD, TICKET, RELIC, AGAIN, EXIT = (f"choice_ent3_{n}" for n in range(1, 6))
SCENE_HASHES = MappingProxyType(
    {
        ENTRY: "ff8472ebe905c486bc3761700822847ec05bcf44f86bbb090d384db5f3861ba0",
        "scene_ent3_1": "e7e916cc7e44957a86351453959eb90ce55721779486786f032eb43c9479b09f",
        "scene_ent3_2": "8cca049e8e487962d72533a2ca7d966fd8db42588b87243a4c77bda221e6d604",
        "scene_ent3_3": "935b117981c52d01a52586e202bd69e1a3785ce16dfda5728fa72ab3dc4fc7f2",
        "scene_ent3_4": "5ae4c7f491cb1f832cba4ea068c96b7d85209d78d4bdf475f47410aafab0074b",
    }
)
CHOICE_HASHES = MappingProxyType(
    {
        GOLD: "7e2010efe603d84efb76a4f252c306bc087d8bd1256e978569bc14032105f5a3",
        TICKET: "5c8fa769ab6f1278e5ece387a4fc01ca735f5f6b1e1946fc382f3c2e08b46dd2",
        RELIC: "0fa65eda0ca30f5b8064fbea31221d35f10798fa754079ce105cf5a3b72f3987",
        AGAIN: "d25cb4a25f682c00278cd4f4ef67b29ec83654082a4e09f0690668aef7ae403f",
        EXIT: "d88e6f3239b35fc1a416fd154b3b0e7bf72b44bbdec765b6e4e8c8148482c54b",
    }
)


@dataclass(frozen=True)
class Recreation:
    program: EventProgram
    tickets: tuple[str, ...]
    relics: tuple[str, ...]
    reservations: frozenset[str]


def invalid():
    return ValueError("暴殄天物需要匹配的基础场景、明确招募券、收藏品效果与资格")


def identifiers(value):
    return type(value) is list and 1 <= len(value) <= 128 and all(type(k) is str and k for k in value)


def compile_recreation(data, value, *, at):
    if (
        type(value) is not dict
        or set(value) != {"program", "tickets", "relics", "eligibility", "evidence"}
        or value["program"] != PROGRAM
        or not all(identifiers(value[k]) for k in ("tickets", "relics", "eligibility"))
        or len(set(value["relics"])) != len(value["relics"])
        or len(set(value["eligibility"])) != len(value["eligibility"])
        or type(at) is not int
        or not 0 <= at < 2**63
        or type(value["evidence"]) is not str
        or not 1 <= len(value["evidence"]) <= 1024
    ):
        raise invalid()
    data.rogue_topics.topic("rogue_1", at=at)
    detail = data.table("roguelike_topic_table")["details"]["rogue_1"]
    if (
        any(fingerprint(detail["choiceScenes"].get(k)) != digest for k, digest in SCENE_HASHES.items())
        or any(fingerprint(detail["choices"].get(k)) != digest for k, digest in CHOICE_HASHES.items())
        or any(k not in data.rogue_recruit.catalog for k in value["tickets"])
    ):
        raise invalid()

    relic_deltas, proofs = [], []
    for item in value["relics"]:
        _, proof = compile_groups(
            data, RelicGroups(((item,),), frozenset(value["eligibility"]), value["evidence"]), at=at
        )
        if data.rogue_relic_archive.entries[item].special:
            raise invalid()
        relic_deltas.append(
            Delta(
                hp=-6,
                gold=data.rogue_gold_relics.require(item) if gold_supported(data, item) else 0,
                squad_capacity=data.rogue_capacity_relics.require(item)
                if capacity_supported(data, item)
                else 0,
            )
        )
        proofs.append(proof)

    stop = Branch(EXIT, CHOICE_HASHES[EXIT], Delta())
    again = Branch(AGAIN, CHOICE_HASHES[AGAIN], Delta())
    leave = Frame("scene_ent3_4", (Branch("choice_leave", LEAVE_DIGEST, Delta()),))
    frames = (
        Frame(
            ENTRY,
            (
                Branch(GOLD, CHOICE_HASHES[GOLD], Delta(hp=-2, gold=6), (("hp", 3),)),
                Branch(TICKET, CHOICE_HASHES[TICKET], Delta(hp=-3), (("hp", 4),)),
                Branch(RELIC, CHOICE_HASHES[RELIC], Delta(hp=-6), (("hp", 7),)),
                stop,
            ),
        ),
        *(Frame(f"scene_ent3_{n}", (again, stop)) for n in range(1, 4)),
        leave,
    )
    program = data.rogue_scenes.compile(EventSpec(PROGRAM, ENTRY, frames, value["evidence"]))
    if program.choices["choice_leave"].target is not None:
        raise invalid()
    digest = fingerprint(
        {
            "data": data.manifest["hash"],
            "at": at,
            "plan": value,
            "program": program.digest,
            "scenes": dict(SCENE_HASHES),
            "effects": proofs,
        }
    )
    program = replace(
        program,
        digest=digest,
        choice_deltas=MappingProxyType(
            {TICKET: (Delta(hp=-3),) * len(value["tickets"]), RELIC: tuple(relic_deltas)}
        ),
        exit_steps=MappingProxyType({frame.scene: 1 if frame is leave else 2 for frame in frames}),
    )
    return Recreation(program, tuple(value["tickets"]), tuple(value["relics"]), frozenset(value["relics"]))
