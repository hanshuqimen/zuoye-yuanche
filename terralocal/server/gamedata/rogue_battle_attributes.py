"""Matched first-theme battle attribute effects, separate from natural supply.

The owned client applies these add/multiply effects during battle. Admission
here binds their complete imported definitions; it neither computes permanent
operator stats nor declares encounter weights, unlocks or acquisition routes.
"""

from types import MappingProxyType

from terralocal.server.gamedata.repository import fingerprint

POLICY = "rogue1-battle-attribute-relics-v1"
# These also participate in the hidden-ending acquisition/transition chain.
# Attribute-only rows are insufficient evidence for their complete effects.
ROUTE_RELICS = frozenset({"rogue_1_relic_m19", "rogue_1_relic_m20", "rogue_1_relic_m21"})
# Per-entry definitions permit smaller authored QA tables while rejecting any
# changed production effect, selector or condition. No official asset is stored.
SOURCES = MappingProxyType({
    "rogue_1_relic_a01": "7f1fd470a0180dc9b58a13764565a05439bafdb98ecfa2ae48c0a4f04015364d",
    "rogue_1_relic_a11": "6d6227e21689e1b2d3987ae9f22b325f9b97027b0102e326a0963c679215c133",
    "rogue_1_relic_a12": "667980c2ef0ac47ce486021ef6df04f8d937eaac5c2801825c5fe0f9a1298e9f",
    "rogue_1_relic_a13": "920607de13436d06ddf93d8e623b8eed4cd06ab33422c6ad90e381fce852e129",
    "rogue_1_relic_a14": "a549bf825cd7fef825583cead671fc6c53bc1587ddf265b54dff50269d468ae7",
    "rogue_1_relic_a15": "586dd416cbe3d2831f52f5fa7bf68b27758e780f677bde183b09a4b8cedcb6c6",
    "rogue_1_relic_a16": "45b4150bd3af7e560ca132acb1ddc3870334e65db8a556f7edad4db61b75e24b",
    "rogue_1_relic_a17": "2f92335a9d5eb3bdfcf45085adb247bf3ffb48b91a4cd492d1062b65a0189d2a",
    "rogue_1_relic_a18": "b145e01184d3d22f593262c2e36b2771f7a930c0009fc37e44995c00e9eb13bd",
    "rogue_1_relic_a19": "8fc4d7653bbf26cc8333b779406a855c0072c49dd4d8e55fcaf37d8960d4b676",
    "rogue_1_relic_a20": "f52485bcdf7c77a783eaae1e3665a5d80dbfa909ebb310072414fa33246872a3",
    "rogue_1_relic_a21": "bf3fc299b1a4c674be7588c90bf91369e7a325f35f3103b7e0d655485b8fd9b3",
    "rogue_1_relic_a22": "e777f33d8472d823aafc714d3341052378e3267f194a9c5ed0f896b2dc5568e3",
    "rogue_1_relic_a31": "2c933246ca675ef35ace6a5aef15b37a1dae5db37cbfdaba777ffac40a8ac2ef",
    "rogue_1_relic_m01": "3494538dd83fce9fc89e011f0c7080e9c8cd2fe094ed7fac442f41c9945e07d2",
    "rogue_1_relic_m02": "ec5f8388cd1ec8d3f233b768f7a7b0463695a30c88be9663a8c555593a52988b",
    "rogue_1_relic_m04": "1edf95156c2db1fe2347e10cf46ccc10994f10e98853bbbd743834113fac4c05",
    "rogue_1_relic_m05": "0ae8de79c348e007f88cfc570d546e5ec5ce783cdaf6a5db66a180e3a13a69e0",
    "rogue_1_relic_m13": "9a414b3eb1f733e144e2f2f20b1dfbd60c3f762cb0db90aca2cdbe772200d6d1",
    "rogue_1_relic_m14": "3985aefcb7c138df11880f1792e73b90f535a07c9b7f81bbe6fb43263d355bc0",
    "rogue_1_relic_n01": "d81026eff447ac89d2e49cbb209172eb25fac069294bae65ace7643b2983c51b",
    "rogue_1_relic_n04": "3e0b4eddcc40427be25941aeb9c88d79b2fea15a43cc63f44c9c6d383cfa673a",
    "rogue_1_relic_p01": "7b7a677a2cebc32067343c940cd8c58742deef52b9388fa3e464d63b2ded7fac",
    "rogue_1_relic_p04": "b8279e9dc14082738a93dd46440c7e991d44a310d7964df503039614ea0d2be7",
    "rogue_1_relic_p05": "6c4115413c9d1fddb981c8a5d8be5cd6609a7d41a444b18a9c3317004430162f",
    "rogue_1_relic_p06": "371a6a1626b41c6d9a5520e7f61366665ff5c90e6990a672bc594fe8c428b58b",
    "rogue_1_relic_p07": "8cee103af1c5927bf07ed9c915c6ac0b4c7767a308baea1ab6054222284babb4",
    "rogue_1_relic_p09": "65158300145584ab4cc111b2acdabb6731cd36f616fcacbe6dd7478050f0525f",
    "rogue_1_relic_p10": "48dde3961e5e67fb823bbf17c3dc1472bdec7c41029e608e7fd9f79368e16754",
    "rogue_1_relic_p11": "6456f65b013157c4fc40bc735d831b6c4e8f50a6115d19a0cf4f07451b0f59c5",
    "rogue_1_relic_p12": "b74cd73b80a11194381368c3c67d75d3fa2924c93df0bc41149170d43b329938",
    "rogue_1_relic_p13": "768949536f8683878c88d3f2b96d4117072ac4ac8658134125a489cedefc1496",
    "rogue_1_relic_p16": "66816c3a7c5691ef6660e5421a5ca7efa17c612eaaf9cf0c9f76ef2066b55938",
    "rogue_1_relic_p17": "e879fb48950c9bfa993d63bc6c864d38c63fe2db8b3a021bc07bf1cbcdeb97eb",
    "rogue_1_relic_p19": "78c62433913e15ba1e0e7659f664ed242552b610ab7ffc6432f10db541da0ecf",
    "rogue_1_relic_p20": "ddf2d4221d1dee4baf045cea0fe248dd9296935a02b7b52ab814fae8f1a42f98",
    "rogue_1_relic_p21": "76694a56d16850f7453e1ef87df2929b5c7b85e92c223e281061d8e66a393223",
    "rogue_1_relic_p22": "b0c3c599f5d89ea7e70a5310e39121db17cdf213cd7c4af85577ca8a0bd3dff3",
    "rogue_1_relic_p23": "75d7938446b11e0bedef93176778e3e5b7f15c9681b4257c80dc01a1d34f5041",
    "rogue_1_relic_p26": "2ddadd3c99a02f262c17135e8ca426640cfc0c74291a315809e016accdddaf4c",
    "rogue_1_relic_p31": "aa5e09d7b83e20a2cd749c279dfa848d864a8206e21cc36c313250c3df337ed8",
    "rogue_1_relic_p33": "c97604618e68048aec66b687c4f07674901b26e6061894f47846c48af62c1695",
    "rogue_1_relic_p34": "1ac8c08f145f50ff99d1c4cc596c21fa3d3cd060949c70614d24244fe9ae443c",
    "rogue_1_relic_p36": "cab5f1aec4bf6a89b1e8bc0be6aaccded82aeae2ea9c7cddcbbdb7c7cd7a601b",
    "rogue_1_relic_p37": "b1207574b48c2d7705e7c5aba43d6738b3e82ce72c0585800cc028f65ec368d2",
    "rogue_1_relic_p38": "72bcf5b8d1595c754a6a4d4166462cdefebbb08258920b01b23886d7124f2230",
    "rogue_1_relic_p39": "e39700912f50c0db864913169ba2668fb0d13897776fb7410924ac8e81023e7d",
    "rogue_1_relic_p40": "a7033aff1dd226ab7c4615b2cc6c04fbf809660b7c4cc06048487f0e111dac2e",
    "rogue_1_relic_p45": "8c3f5216651bd21dbe810097aaecfb396f59019e8499e980089a5f7949b5d388",
})


def invalid():
    return ValueError("首主题战斗属性收藏品效果与已核对版本不一致")


class FirstThemeBattleAttributes:
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
    data.rogue_battle_attributes.require(key)
    return True
