"""Frozen first-theme ordinary global-buff capabilities, independent of supply.

The client copies each normal buff's complete blackboard and applies its own
target filters. No permanent stat changes, reward grants, stacking formula,
encounter eligibility or merchant price is inferred by this catalog.
"""

from types import MappingProxyType

from terralocal.server.gamedata.repository import fingerprint

POLICY = "rogue1-normal-global-buff-relics-v1"
# Special relics, missing conditions, challenge and boss-related sources need
# their own complete contracts. Exclusion is not evidence of absent client code.
EXCLUDED_RELICS = frozenset({
    "rogue_1_relic_c01",
    "rogue_1_relic_c02",
    "rogue_1_relic_c16",
    "rogue_1_relic_m18",
    "rogue_1_relic_sp02",
    "rogue_1_relic_sp03",
    "rogue_1_relic_sp04",
    "rogue_1_relic_sp05",
    "rogue_1_relic_sp06",
    "rogue_1_relic_sp07",
})
SOURCES = MappingProxyType({
    "rogue_1_relic_a02": "e2056536550f6515a33ef7755c26b766673e1b1b8d5ef2e13691060c6d974ffa",
    "rogue_1_relic_a03": "8a9747d49e0317d16a0b1df106b14becc4808ebe5417d185d84f83be3779ad3f",
    "rogue_1_relic_a04": "e7a84fcfad0220a5d535f8d65eb6bc351e28cf1dae21ce0433506664499bf9f9",
    "rogue_1_relic_a05": "a1c73018aca83b7865746b50291c6b922a4215af1215abb3e6d918671308f385",
    "rogue_1_relic_a06": "c1fa62e965d7e0e3d662d74c1ba1db855cb8aa757056963b789bed37ff132dff",
    "rogue_1_relic_a07": "7856291919b9b7249d74c465fae0f579fd03c54da7fc0f20e3c08e596f4bc560",
    "rogue_1_relic_a08": "0c08d2ab7e5f3e891e35d45df9ada5de4ae70ed2862e2d65d74ddb5ed4be015c",
    "rogue_1_relic_a09": "23c6dfa4fd8a29d6c7462d1454825c58e4f48d23adfa4f473649ae0ce58c80c6",
    "rogue_1_relic_a10": "b9494f3bb37524549e50f8195baf1d2eb24fa11fc7396dbe4a20b59d4d56df36",
    "rogue_1_relic_a29": "9574278d985bc6e282dca535a54c4328bf444b9ba893a64a03753f7093600c78",
    "rogue_1_relic_a30": "96f62f31a4680f849c7d69faa7e4388ef5f9d3d3e7eec5fbf802c1fcccb08cae",
    "rogue_1_relic_a32": "05eea2d6753328cf61b234f1cf63610f51959e937fe6841edd0beaffcb44f105",
    "rogue_1_relic_a33": "a03fc144d70dc56c0ec794828d3413c25a9f8567f7cfb5c9a95eb4c92c6097f1",
    "rogue_1_relic_a34": "d1dddf3051cf7b919aa16aacce350680bca9c2a2b94a53aac6ee97de2f909382",
    "rogue_1_relic_m06": "79391d9f136ee15e7fff100a0343d1fe16303ae59d47d482fc762e29392c5018",
    "rogue_1_relic_n03": "73d2b8eab12b09c351565582795fb7351b670a8fdcbc74227ade375e34ed7295",
    "rogue_1_relic_n05": "592f86360b73f4432573b9dd3a0109e5783fcf99936ae441c03269c481814e7b",
    "rogue_1_relic_n10": "fa213fc5642365edd1e36911c131d767f2239b4bf19c4c2aac6fe0aaacc7c8c8",
    "rogue_1_relic_n12": "13aa160bf8bb71f658e4285c17755f79a9889868b32fa00522cc1a85a649fbc4",
    "rogue_1_relic_n14": "bdd1ca6bb848c76a8c0f96fd3ece09c368a415725220a8228edaa1f9d5102e62",
    "rogue_1_relic_n15": "08adea4faae918ca40cf6929b0e75fc716299858f8abd71c612e394f5c48ed12",
    "rogue_1_relic_p08": "4145d2a918545d7462d4252b59689b281cdb5ae0dcd8747e8a546c90f2db2fc8",
    "rogue_1_relic_p15": "c842d9e63b8d4ef8747158b3e68976294cbfda1047ae4ac15adef0110f5169cb",
    "rogue_1_relic_p18": "59bd59789f3bc1150c2d49ecf1b09c0747b56109f8ef2607ed4fc87dea555d40",
    "rogue_1_relic_p24": "b56b1a2afd282cc8c66a7bb8b93bfdab2e96ed094ec299654785a08bd063c548",
    "rogue_1_relic_p32": "fd788096fc874a6064113609e8860e82611271d424bb0b79b2010bbafdc4d78a",
    "rogue_1_relic_p42": "831e698b030991cb7d638041ada3dc51f945e8f3e6d0401666241e2c91f1942f",
    "rogue_1_relic_p43": "03615fc226264faf01057f95c861a8df0be7cdf4f57aa546fb135a1355d1fd30",
    "rogue_1_relic_p44": "d57b943fc4cf3f9888c5b9094dcae43f7a7e0919d2d619a9d4ee76b94291f845",
    "rogue_1_relic_q18": "059565bf65c9e7bd39a928bae2292265d27d7c964db88836979d562379695d05",
    "rogue_1_relic_q19": "df391630bcff54e762bcac10cbbc32e374e9812a88d50b5a800531e121c5b721",
    "rogue_1_relic_q20": "a1d62cd83be1ed6d177b2103618fa3251beff7634d0ebc99196a96e82c7cac16",
    "rogue_1_relic_q21": "a482d8e700716f187556b93487c40903d02671a6379f6876c1a55ba728a61c41",
    "rogue_1_relic_q22": "a9bd4134d0cab0b670813deb1ecdb9824a806087e693d2b5a1a14e6b0dee79a6",
    "rogue_1_relic_q23": "87d1ff951f4a719047faf1583e895653f69ec017f56dc9ded47b3712a7d5e4ee",
    "rogue_1_relic_q24": "18918d25134316dd9a1f6e605178f82f3b6b17f5e0703e2e27fd3761eb38174a",
    "rogue_1_relic_q25": "50a19d2fef6b6055ce78cf8adf4dc5651f5f261a7e709bf778248b36478106e8",
    "rogue_1_relic_q29": "abbeecc377ec64a0d1437309ee3707666f167b292b2663842d38d54cdaf7e7b4",
    "rogue_1_relic_q30": "bfbed831ff548a947c117db259538a32768408fbfcd1ff2733afbf3684531937",
    "rogue_1_relic_q31": "d7a7fd7f0c0ef1401e180ef2445c2d84eea64abf0dcc74f49d3138f814370ab7",
    "rogue_1_relic_q36": "427eb9b63b0c1dda18d2499e311a4dca73db5b0491ca1005b2fed30c2388dc26",
    "rogue_1_relic_q37": "d8e2b764de7807fb6fbfa1aa43a748867062245a37ab5df3aabf3db8251c597f",
})


def invalid():
    return ValueError("首主题全局战斗收藏品效果与已核对版本不一致")


class FirstThemeGlobalBuffs:
    def __init__(self, data):
        data.rogue_topics.topic("rogue_1")
        admitted, enrollments = {}, {}
        try:
            detail = data.table("roguelike_topic_table")["details"]["rogue_1"]
            for key, expected in SOURCES.items():
                if key not in detail["items"]:
                    continue
                source = {"effect": detail["relics"][key], "conditions": detail["relicParams"][key],
                          "item_type": detail["items"][key]["type"]}
                if (detail["items"][key].get("id") != key or source["item_type"] != "RELIC"
                        or source["effect"].get("id") != key
                        or fingerprint(source) != expected):
                    raise invalid()
                admitted[key] = expected
                entry = data.rogue_relic_archive.entries[key]
                if entry.special:
                    raise invalid()
                at = 0
                if entry.enrollment is not None:
                    enroll = detail["enrolls"][entry.enrollment]
                    at = enroll["enrollTime"]
                    if (enroll["enrollId"] != entry.enrollment or type(at) is not int
                            or not 0 <= at < 2**63):
                        raise invalid()
                enrollments[key] = at
        except (KeyError, TypeError, AttributeError) as exc:
            raise invalid() from exc
        self.entries = MappingProxyType(admitted)
        self.enrollments = MappingProxyType(enrollments)
        self.data_hash = data.manifest["hash"]
        self.fingerprint = fingerprint({"policy": POLICY, "data": self.data_hash, "sources": admitted,
                                        "archive": data.rogue_relic_archive.fingerprint, "enrollments": enrollments})

    def require(self, key):
        if type(key) is not str or key not in self.entries:
            raise invalid()

    def require_open(self, key, at):
        self.require(key)
        if type(at) is not int or not self.enrollments[key] <= at < 2**63:
            raise invalid()


def supported(data, key):
    """Only a capability check; the run driver must still prove ownership."""
    if key not in SOURCES:
        return False
    data.rogue_global_buffs.require(key)
    return True
