"""Reviewed first-theme intrinsic availability, not a generic null-text rule.

This explicit set is cross-checked per item against the theme's public archive,
normal merchant terms and complete admitted effects. It is a local canonical
availability profile, not an official server packet or random supply table.
"""

from dataclasses import dataclass
from types import MappingProxyType

from terralocal.server.gamedata.repository import fingerprint

POLICY = "rogue1-reviewed-base-relic-availability-v1"
SOURCE = "https://prts.wiki/w/傀影与猩红孤钻/长生者宝盒"
SOURCES = MappingProxyType({
    "rogue_1_relic_a11": ("异铁小圆盾", 8, "a5671d7079548f30ffb850b6860c8e23f37d2c7ee50b66efb462be3dcc80497a"),
    "rogue_1_relic_a14": ("皇帝的恩宠", 8, "0462383dd36b3ecea7bff205c7a85d77cff3be712d2e791870a2ba1caa0a9a93"),
    "rogue_1_relic_a17": ("显圣吊坠", 8, "c99cba8051dd761e5fd211d5199906787c78c86f81cbf21e1a5c29c2c566cf4d"),
    "rogue_1_relic_a20": ("难闻的止血剂", 8, "0be872aa0beaf308f755473599f8a9335ba3bccb95b78d3e61c55e285b641dd9"),
    "rogue_1_relic_a35": ("乌萨斯列巴", 8, "bb77859ec04584b712b18d72585ae3e11ca63eef8f9720cffd22a2636395c124"),
    "rogue_1_relic_a36": ("苦行者泡芙", 8, "4858cc60e3d82c14a9e2dbd6217a26f29e766f9eab8555cdd92ee6a35a13cc24"),
    "rogue_1_relic_a39": ("高卢小圆饼", 12, "bbc982edc0dc48d8cb94e6fb435eb784ef5302dc3cd764109d768e8cc3489f7f"),
    "rogue_1_relic_n04": ("“迷醉荷谟伊”", 16, "9906695df2cb484a1341ba0012df09937361528b8d0334fabdceedf36e7f1065"),
    "rogue_1_relic_p01": ("钝爪-突破", 8, "78637c8c36fd87181b4dd18212d1711b1ba0ac965a870c5d122d1c3f9480e7e6"),
    "rogue_1_relic_p06": ("折戟-突破", 8, "232ec1975de454263c334d30aec39321d90a60c1f9d112698fe0d5249a3d7745"),
    "rogue_1_relic_p11": ("铁卫-突破", 8, "3952481cd4ceb121e31e6f11700c853d7287b79236037a9c2353098cfcfe1cb4"),
    "rogue_1_relic_p13": ("铁卫-不动", 12, "c212fe8451d16b337c08d491d08ed55e9de87f9d6d13b259b675f57106e102d8"),
    "rogue_1_relic_p16": ("残弩-突破", 8, "579c50d9bbcea5e99cc40735c505cbc34d67e9a9971fc291ba648048bd169fd3"),
    "rogue_1_relic_p21": ("断杖-突破", 8, "b9e9b012e0d53e951664cfbbfad2324aebee25160ef65cc032cd2d056e913a93"),
    "rogue_1_relic_p23": ("断杖-咏唱", 12, "eb3142dcd02f7e7f73c5f9a3901253bc29ed8f94dceb3b8aeec59db21abf8e47"),
    "rogue_1_relic_p26": ("支柱-突破", 8, "791ede5dc19e847485dff3842d15af8916eb51c587f5ac280293d8fd3bd908e4"),
    "rogue_1_relic_p31": ("医者-突破", 8, "980c1d6c2441fc3f54c8bd607853ae6e6bfdc502f39382cb6edaa3ceb2f41da9"),
    "rogue_1_relic_p33": ("医者-强效试剂", 12, "b57730e0edc7b96cba2ba15f6538eb62390408bdfe2df55c5bf962ae16147554"),
    "rogue_1_relic_p36": ("锈刃-突破", 8, "1203fce118b3460e708bfe0b16b7681b1f80c9821a66fd299a7183b00a9a5f40"),
    "rogue_1_relic_p38": ("锈刃-单兵", 12, "7d80d176486d94a449aa7d44d39d9816e245b88ff939164ab2be1ab30ab89df7"),
    "rogue_1_relic_p45": ("撕扯之手", 16, "1b6dfb3e08c6cc94e93ca0ef4d078c607f63e71b4ceca5c57f904d2b0b44faac"),
})


def invalid():
    return ValueError("首主题基础收藏品资格与逐项核对的完整规则不一致")


def available(data):
    if data is None or "roguelike_topic_table" not in data.manifest.get("tables", {}):
        return False
    items = data.table("roguelike_topic_table")["details"].get("rogue_1", {}).get("items", {})
    # Capability detection only. Any reviewed name declares the profile and
    # reaches the strict complete-set compiler; a missing sibling must fail.
    return any(type(items.get(key)) is dict and items[key].get("name") == row[0] for key, row in SOURCES.items())


@dataclass(frozen=True)
class BaseAvailability:
    opened: bool
    current: int = 0
    target: int = 1

    def wire(self):
        # No condition counter is invented. Archive state and actual discovery
        # use the independently recovered M194808/M154269 consumers.
        return {"state": int(self.opened), "progress": []}


class FirstThemeBaseRelics:
    def __init__(self, data):
        topic = data.rogue_topics.topic("rogue_1")
        catalog = data.rogue_merchant_relics  # Validates complete effect adapters.
        openings = {}
        try:
            detail = data.table("roguelike_topic_table")["details"]["rogue_1"]
            for key, (name, price, expected) in SOURCES.items():
                item = detail["items"][key]
                identity = {f: item[f] for f in ("id", "type", "iconId", "rarity", "unlockCondDesc")}
                archive = detail["archiveComp"]["relic"]["relic"][key]
                ref, merchant = data.rogue_relic_archive.entries[key], catalog.entries[key]
                if (item["name"] != name or identity["id"] != key or identity["type"] != "RELIC"
                        or identity["unlockCondDesc"] is not None or ref.special
                        or fingerprint({"item": identity, "archive": archive}) != expected
                        or type(price) is not int or price not in (8, 12, 16) or merchant.price != price):
                    raise invalid()
                openings[key] = max(topic.start, merchant.opens_at)
        except (KeyError, TypeError, AttributeError) as exc:
            raise invalid() from exc
        self.openings = MappingProxyType(openings)
        self.fingerprint = fingerprint({"policy": POLICY, "data": data.manifest["hash"], "source": SOURCE,
            "reviewed": dict(SOURCES), "merchant": catalog.fingerprint, "openings": openings})

    def evaluate(self, at):
        if type(at) is not int or not 0 <= at < 2**63:
            raise invalid()
        return MappingProxyType({key: BaseAvailability(at >= opens) for key, opens in self.openings.items()})
