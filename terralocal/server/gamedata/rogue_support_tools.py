"""Reviewed first-theme tool identities, not shop prices or a random pool.

Native default consumers read CurrentData.Inventory.trap as {id, ts}.
Counts below are matched to the imported usage and this theme's tool archive;
admission is not proof that a battle has consumed those counts.
"""

from dataclasses import dataclass
from types import MappingProxyType

from terralocal.server.gamedata.repository import fingerprint

POLICY = "rogue1-reviewed-support-tool-bindings-v1"
SOURCES = MappingProxyType({
    "rogue_1_active_tool_1": ("trap_009_battery", 1, "9468ea956a5c2017ae7a985cfc2a3f9768b8059e8622fa14b5c56e9800d08263"),
    "rogue_1_active_tool_2": ("trap_012_mine", 3, "4b2134498e315ba52a3b518949c8c432b318b14ad3bf090de70bea7901e00a97"),
    "rogue_1_active_tool_3": ("trap_018_bomb", 1, "e5148d3102a0109061ffc6df129f6da6bacb6e646f5db8cb8887d5a97e15e416"),
    "rogue_1_active_tool_4": ("trap_031_sleep", 1, "943f0dcda286b24e45fc95fbce7f515bb11c1be0b3c801add1ee369f94ce04ec"),
    "rogue_1_active_tool_5": ("trap_052_slowfd", 1, "acb6a494915d36d728e0e967807d1cdde776f784edf36d78e51d213152e1b804"),
    "rogue_1_active_tool_6": ("trap_053_airbomb", 2, "57aa5ee58f66800c69ee09132da076b92e92c92d88b0e6ffa0aeddcb0efb72f8"),
})


def invalid():
    return ValueError("首主题支援道具与逐项核对的物品、装置及档案不一致")


@dataclass(frozen=True)
class SupportTool:
    item_id: str
    trap_id: str
    battle_count: int
    opens_at: int


class FirstThemeSupportTools:
    def __init__(self, data):
        topic = data.rogue_topics.topic("rogue_1")
        entries = {}
        try:
            detail = data.table("roguelike_topic_table")["details"]["rogue_1"]
            for key, (trap_id, count, expected) in SOURCES.items():
                item, trap = detail["items"][key], detail["traps"][key]
                archive = detail["archiveComp"]["trap"]["trap"][key]
                if (item["id"] != key or item["type"] != "ACTIVE_TOOL" or item["iconId"] != key
                        or trap["itemId"] != key or trap["trapId"] != trap_id
                        or archive["trapId"] != key or archive["enrollId"] is not None
                        or type(count) is not int or not 1 <= count <= 8
                        or fingerprint({"item": item, "trap": trap, "archive": archive}) != expected):
                    raise invalid()
                entries[key] = SupportTool(key, trap_id, count, topic.start)
            if not entries or len({v.trap_id for v in entries.values()}) != len(entries):
                raise invalid()
        except (KeyError, TypeError, AttributeError) as exc:
            raise invalid() from exc
        self.entries = MappingProxyType(entries)
        self.fingerprint = fingerprint({"policy": POLICY, "data": data.manifest["hash"],
            "bindings": dict(SOURCES), "opening": topic.start})

    def require(self, key, at):
        if (type(key) is not str or key not in self.entries or type(at) is not int
                or not 0 <= at < 2**63 or at < self.entries[key].opens_at):
            raise invalid()
        return self.entries[key]
