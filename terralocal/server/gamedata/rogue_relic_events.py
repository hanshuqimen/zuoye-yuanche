"""Reviewed complete fixed-attribute events; no inferred natural encounter pool."""

from dataclasses import replace
from types import MappingProxyType

from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.gamedata.rogue_events import LEAVE_DIGEST, Branch, Delta, EventSpec, Frame
from terralocal.server.gamedata.roguelike import invalid

POLICY = "rogue1-fixed-attribute-event-source-v1"
# Each tuple binds the complete entry menu, exact result edges and all effects.
# Grant-free alternatives are part of the event, including the stone's third
# narrative choice. Attribute definitions are validated by their existing catalog.
SOURCES = (
    ("rogue1-event-stone-v1", "scene_4_enter", (
        ("choice_4_1", "scene_4_1", "rogue_1_relic_m05", Delta()),
        ("choice_4_2", "scene_4_2", "rogue_1_relic_m04", Delta()),
        ("choice_4_3", "scene_4_3", None, Delta()))),
    ("rogue1-event-book-v1", "scene_bottle1_enter", (
        ("choice_bottle1_1", "scene_bottle1_1", "rogue_1_relic_m13", Delta()),
        ("choice_bottle1_2", "scene_bottle1_2", None, Delta(hope_max=2)))),
    ("rogue1-event-statue-v1", "scene_bottle2_enter", (
        ("choice_bottle2_1", "scene_bottle2_1", None, Delta(hp=3)),
        ("choice_bottle2_2", "scene_bottle2_2", "rogue_1_relic_m14", Delta()))),
)
PROGRAMS = frozenset(row[0] for row in SOURCES)
RELICS = MappingProxyType({(key, choice): item for key, _, branches in SOURCES
                          for choice, _, item, _ in branches if item is not None})
CHOICE_HASHES = MappingProxyType({
    "choice_4_1": "1d467a36ea5c148c7b2b7a4bbd8ed8de14bb132c334a6fc2fe93a02e5072f8af",
    "choice_4_2": "fe6a23ecfdcc032fd4f20bd9cb9c8ca6f3621ceec6063daa882be1beb9032d1f",
    "choice_4_3": "d48daab27b5dac3d9070e8f826aae4e4d251c0ace2ebeaad964e254050771083",
    "choice_bottle1_1": "8915392513ea0f0f17a59a4e9f3591c0c9af624ccf319b51aac734db85ffb3bc",
    "choice_bottle1_2": "50e8b6859f37ccc4b600fb20a12e6aeba380e13f720a7a155a83dec4a0f70798",
    "choice_bottle2_1": "8354af84dcf0a8d9fbce3a54bad011803ab30e79759c5a8ca650dabb5f0677f8",
    "choice_bottle2_2": "7598280be60d4aa20509c0b9a552730aa8f2e4b69baf342514181570434a1d62",
})


def programs(data):
    catalog, attributes = data.rogue_scenes, data.rogue_battle_attributes
    detail = data.table("roguelike_topic_table")["details"]["rogue_1"]
    result = {}
    for key, entry, rows in SOURCES:
        effects = {}
        for choice, _, item, _ in rows:
            if item is None:
                continue
            display = detail["choices"].get(choice, {}).get("displayData")
            if (not isinstance(display, dict) or display.get("type") != "ITEM"
                    or display.get("itemId") != item):
                raise invalid("固定收藏品事件未匹配明确ITEM来源")
            attributes.require(item)
            effects[item] = attributes.entries[item]
        spec = EventSpec(key, entry, (Frame(entry, tuple(
            Branch(choice, CHOICE_HASHES[choice], delta) for choice, _, _, delta in rows)),
            *(Frame(target, (Branch("choice_leave", LEAVE_DIGEST, Delta()),)) for _, target, _, _ in rows)),
            "Complete frozen choice/ITEM rows and existing matched attribute effects; "
            "PRTS IS2 stone/book/statue events: https://prts.wiki/w/傀影与猩红孤钻/事件一览 ; "
            "all menu alternatives, fixed grants only, no natural encounter weights or eligibility claim")
        compiled = catalog.compile(spec)
        if any(catalog.choices[choice].target != target for choice, target, _, _ in rows):
            raise invalid("固定收藏品事件的后继场景未匹配")
        result[key] = replace(compiled, digest=fingerprint({"policy": POLICY, "graph": compiled.digest,
            "grants": {choice: item for choice, _, item, _ in rows}, "attributes": effects}))
    return MappingProxyType(result)
