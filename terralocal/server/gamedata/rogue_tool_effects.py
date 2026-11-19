"""Reviewed first-theme tool battle effects, separate from existing shop quotes."""

import json
from dataclasses import dataclass
from types import MappingProxyType

from terralocal.server.gamedata.repository import canonical, fingerprint

POLICY = "rogue1-reviewed-tool-battle-effects-v1"
SOURCES = MappingProxyType({
    "rogue_1_active_tool_1": ("406d6c9306c3d1cd563573bf1251e3596cf688ba971049462cc69c40eb83faf2", "d37081e7a033c791323aea755c5b988ae681e84da24abdbaf03c6865d06b08d1"),
    "rogue_1_active_tool_2": ("06df4d97fa2a21a4822d9d6fad6fe9a17c41bd1277c41d747a3016ae0b0d3cfa", "1b02c14524dc914e95e234963b5fdcf6df4b5ec734613c421cd011b04cbf5d3f"),
    "rogue_1_active_tool_3": ("5a7278ad2f599e904032dc424d40c5f452a145f66ed2e91b6a1f4198edf2e194", "53a0c217e2948d25cd398387845e13c5e10067cfa2ac28039672a058d1514d56"),
    "rogue_1_active_tool_4": ("99582e690aeb6b82ca60b05769551b5a14136242e1039ad409bc76457229928b", "687c26dd38e0e708aff2e288fdaf3e078c955f29c4bd483345d005700f43dac4"),
    "rogue_1_active_tool_5": ("a4ccdf21152d848666ace7debe22d6ed1789b1f2eb0b35176dadab263cf798a0", "f1e1dbcfb993dc874793c691a9bc43163cbb8c01f168fea7321300ea113a1c81"),
    "rogue_1_active_tool_6": ("25bf1ab8e87d589ff08f47876f9abf32ab5932260fc3c4df953d3d632a1394b9", "2298e46c0e7fcebe9f6e8f5b2e9d1bc232b1fce63e9aa5765758b306bfbe27d5"),
})


def invalid():
    return ValueError("支援道具战斗效果与已核对的完整效果、装置模板不一致")


@dataclass(frozen=True)
class ToolEffect:
    item_id: str
    trap_id: str
    level: int
    skill_index: int
    count: int
    encoded_buffs: bytes

    def wire(self):
        # A response cannot modify the catalog or another battle's projection.
        return json.loads(self.encoded_buffs)


class FirstThemeToolEffects:
    def __init__(self, data):
        self.tools = data.rogue_support_tools
        entries = {}
        try:
            detail = data.table("roguelike_topic_table")["details"]["rogue_1"]
            if set(SOURCES) != set(self.tools.entries):
                raise invalid()
            for key, (effect_hash, token_hash) in SOURCES.items():
                tool = self.tools.entries[key]
                relic, token = detail["relics"][key], data.characters[tool.trap_id]
                buffs = relic["buffs"]
                if (fingerprint(relic) != effect_hash or fingerprint(token) != token_hash
                        or token["profession"] != "TRAP" or type(buffs) is not list or len(buffs) != 1
                        or buffs[0]["key"] != "misc_insert_token_card"):
                    raise invalid()
                board = buffs[0]["blackboard"]
                if type(board) is not list or [v["key"] for v in board] != ["token_key", "level", "skill", "cnt"]:
                    raise invalid()
                if (type(board[0]["value"]) not in (int, float) or board[0]["value"] != 0
                        or board[0]["valueStr"] != tool.trap_id):
                    raise invalid()
                values = []
                for value in board[1:]:
                    number = value["value"]
                    if (type(number) not in (int, float) or not -1 <= number <= 8
                            or int(number) != number or value["valueStr"] is not None):
                        raise invalid()
                    values.append(int(number))
                level, skill, count = values
                if (level != 1 or count != tool.battle_count or not 1 <= count <= 8
                        or not token["phases"] or token["phases"][0]["maxLevel"] < level
                        or type(token["skills"]) is not list
                        or skill != (0 if token["skills"] else -1)):
                    raise invalid()
                entries[key] = ToolEffect(key, tool.trap_id, level, skill, count, canonical(buffs))
        except (KeyError, TypeError, AttributeError, IndexError) as exc:
            raise invalid() from exc
        self.entries = MappingProxyType(entries)
        self.fingerprint = fingerprint({"policy": POLICY, "data": data.manifest["hash"],
            "tools": self.tools.fingerprint, "effects": dict(SOURCES)})

    def require(self, key, at):
        self.tools.require(key, at)
        if key not in self.entries:
            raise invalid()
        return self.entries[key]
