"""First-theme base merchant terms from reviewed per-item source records.

This catalog distinguishes mechanically admitted effects from normal merchant
availability. Prices/exclusions are community observations cross-checked with
the frozen client identities, not a recovered official server table. It does
not define random weights, floor distribution, discounts or a map generator.
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.gamedata.rogue_capacity_relics import SOURCES as CAPACITY_RELICS
from terralocal.server.gamedata.rogue_gold_relics import SOURCES as GOLD_RELICS
from terralocal.server.gamedata.rogue_recruit_costs import FILTERS
from terralocal.server.gamedata.rogue_resource_relics import SOURCES as RESOURCE_RELICS
from terralocal.server.gamedata.rogue_shops import Offer, compile_shop
from terralocal.server.gamedata.roguelike import identifier

POLICY = "rogue1-normal-base-merchant-relics-prts-v1"
SOURCE = "https://prts.wiki/w/傀影与猩红孤钻/长生者宝盒"

# Per-ID facts: base source-stone ingots, or None for a normal merchant exclusion.
# Digests bind actual item identity and archive reference; no official tables copied.
SOURCES = MappingProxyType({
    "rogue_1_relic_a01": (None, "f71cebe4996a1b9caaa51a95938bda6fc11e9ef115f4981c05c8bb2a42148179"),
    "rogue_1_relic_a11": (8, "a5671d7079548f30ffb850b6860c8e23f37d2c7ee50b66efb462be3dcc80497a"),
    "rogue_1_relic_a12": (12, "41ad051afc0c12d27e081a59dc687da90b7569f88c1e620f5339c7e46791bc27"),
    "rogue_1_relic_a13": (None, "afa4a9ac1f3d5318399f32fa93ad94ed39a3a57a3e670aac03131ca32ab448bf"),
    "rogue_1_relic_a14": (8, "0462383dd36b3ecea7bff205c7a85d77cff3be712d2e791870a2ba1caa0a9a93"),
    "rogue_1_relic_a15": (12, "2fcd2622808670817b8fe86dbee5f70406d679373a90e8f9d8caedf3d78a8b54"),
    "rogue_1_relic_a16": (None, "4fc2b2ff87c6da70657e0267736c589fcab0140f7bd0d2cb63ce19fb40c17d1a"),
    "rogue_1_relic_a17": (8, "c99cba8051dd761e5fd211d5199906787c78c86f81cbf21e1a5c29c2c566cf4d"),
    "rogue_1_relic_a18": (12, "829ee448059712c5f8967e977bccd8fc96c0de645840a38f46fcb7d9dd51c4db"),
    "rogue_1_relic_a19": (None, "25f81dafd15fac63f2da707160179d4b1f17546bab92f46cbc457c8a9c8983c7"),
    "rogue_1_relic_a20": (8, "0be872aa0beaf308f755473599f8a9335ba3bccb95b78d3e61c55e285b641dd9"),
    "rogue_1_relic_a21": (12, "719acac3758cff29baea8ed8b8bb83da2d9334af4d06e8631460736daaffd284"),
    "rogue_1_relic_a22": (None, "fa952a83c64629530edd5c05af18a3c8bcef84db4e2f82d721ef4c2e9d63fe83"),
    "rogue_1_relic_a31": (12, "2d58d0776edad4d655ddfbbf7f3d3f19b9b87c7a9fd1d49a34ed1a05d9b9bfef"),
    "rogue_1_relic_a35": (8, "bb77859ec04584b712b18d72585ae3e11ca63eef8f9720cffd22a2636395c124"),
    "rogue_1_relic_a36": (8, "4858cc60e3d82c14a9e2dbd6217a26f29e766f9eab8555cdd92ee6a35a13cc24"),
    "rogue_1_relic_a37": (8, "204c94d60b65b49df10b63f42daeebe24971766693aaf7ca1f2f132995a57544"),
    "rogue_1_relic_a38": (12, "52f86673eb6d819f72da59d11422b33d2af3f108a4c4577062a26ce1f6d66f7e"),
    "rogue_1_relic_a39": (12, "bbc982edc0dc48d8cb94e6fb435eb784ef5302dc3cd764109d768e8cc3489f7f"),
    "rogue_1_relic_a40": (16, "ef95c090f00a8c2905a84368d6591a5277e4db44e7730c689ae4c7d3d7b58dcc"),
    "rogue_1_relic_m01": (None, "73188073831fb9ead7e9f46692ad47f717a69781d763353d69143cc2600851cf"),
    "rogue_1_relic_m02": (None, "9d85646e9e61ed8f8995fbb9dd279986d6f48a1e2406ce4ea63f24e372c3b22f"),
    "rogue_1_relic_m04": (None, "93223ae94d12d76a7a2f5a745d358cfe6faddb214bba3d924be77e36c05033a4"),
    "rogue_1_relic_m05": (None, "23dcd55c93f0b083f9b0ea5adbdd8f4773b5213511b50a75dfa23e773b245809"),
    "rogue_1_relic_m13": (None, "4d7a156dc4d266447e7f160bc198693b54b1dd75525d3cc5db7f61c0f47c828a"),
    "rogue_1_relic_m14": (None, "b5a679a2732d8a959262ab9272f166276c0593727272b59f83732e9ab42b8776"),
    "rogue_1_relic_n01": (None, "11e9bb3f2b803d4ca3e686cfbe6ee7b20ecf50997ff53d2495f9f49bb15f14ca"),
    "rogue_1_relic_n04": (16, "9906695df2cb484a1341ba0012df09937361528b8d0334fabdceedf36e7f1065"),
    "rogue_1_relic_p01": (8, "78637c8c36fd87181b4dd18212d1711b1ba0ac965a870c5d122d1c3f9480e7e6"),
    "rogue_1_relic_p04": (12, "1ade757cd53f6da9e6930bdccfd1f4b19752911927c148547d4871b7a81058e5"),
    "rogue_1_relic_p05": (16, "f160de391de04dcf583eaf52dcca53d278b2631c1a372be5e9931d4f0a425311"),
    "rogue_1_relic_p06": (8, "232ec1975de454263c334d30aec39321d90a60c1f9d112698fe0d5249a3d7745"),
    "rogue_1_relic_p07": (8, "87b5d9c07958f2e1a8f1a7f99576e148a2adbeb208ae90973f5fbe66f53ad472"),
    "rogue_1_relic_p09": (12, "7383f53e7ac1d4ebd60c86ac1a2c2858980786235d1941db6d8426b0571f9501"),
    "rogue_1_relic_p10": (16, "02c49438b0f1b7bef051cd0ce18861421b6f961fbf5f78f3e8e4e0d504ab57a6"),
    "rogue_1_relic_p11": (8, "3952481cd4ceb121e31e6f11700c853d7287b79236037a9c2353098cfcfe1cb4"),
    "rogue_1_relic_p12": (8, "ddf11547270a46871621e1e0f09cded57b81428a5cef841e5fe027852418311d"),
    "rogue_1_relic_p13": (12, "c212fe8451d16b337c08d491d08ed55e9de87f9d6d13b259b675f57106e102d8"),
    "rogue_1_relic_p16": (8, "579c50d9bbcea5e99cc40735c505cbc34d67e9a9971fc291ba648048bd169fd3"),
    "rogue_1_relic_p17": (8, "b141729a662815cd36157665d88dd48bb73f815ff65ff0d83a7afd5f1ce7bf98"),
    "rogue_1_relic_p19": (12, "6b690fe638cebac8e016522c63431ce0790d9fc382bba356f020e77ee275b3b7"),
    "rogue_1_relic_p20": (16, "4e4affab3d31c6c691d8bbf0881b0cdbb0b23a9a3b32d2776bc61f47b5a25f00"),
    "rogue_1_relic_p21": (8, "b9e9b012e0d53e951664cfbbfad2324aebee25160ef65cc032cd2d056e913a93"),
    "rogue_1_relic_p22": (8, "f149f6a22e3ca11cb2fc60be221c0ddf1c1ee151481bc8fcd972d90958e0d780"),
    "rogue_1_relic_p23": (12, "eb3142dcd02f7e7f73c5f9a3901253bc29ed8f94dceb3b8aeec59db21abf8e47"),
    "rogue_1_relic_p26": (8, "791ede5dc19e847485dff3842d15af8916eb51c587f5ac280293d8fd3bd908e4"),
    "rogue_1_relic_p31": (8, "980c1d6c2441fc3f54c8bd607853ae6e6bfdc502f39382cb6edaa3ceb2f41da9"),
    "rogue_1_relic_p33": (12, "b57730e0edc7b96cba2ba15f6538eb62390408bdfe2df55c5bf962ae16147554"),
    "rogue_1_relic_p34": (12, "3373793e4d7b072413419c47ad8198989fdccf590a893a05bffa8ceb2c466bbb"),
    "rogue_1_relic_p36": (8, "1203fce118b3460e708bfe0b16b7681b1f80c9821a66fd299a7183b00a9a5f40"),
    "rogue_1_relic_p37": (8, "f9cf73bfeb1ffcd9660fda3fdf0df85d89c4df3d7d95df9d03410be23c624f4a"),
    "rogue_1_relic_p38": (12, "7d80d176486d94a449aa7d44d39d9816e245b88ff939164ab2be1ab30ab89df7"),
    "rogue_1_relic_p39": (12, "ce74bed363cfbf71296325f0f37180bb12ea522c70ba9af846353623396b9a9c"),
    "rogue_1_relic_p40": (16, "7714ba575f424d6f23053d9b6d39d5cfb08fbe6122c9fe3848ea08483ea066d3"),
    "rogue_1_relic_p45": (16, "1b6dfb3e08c6cc94e93ca0ef4d078c607f63e71b4ceca5c57f904d2b0b44faac"),
    "rogue_1_relic_r25": (12, "4ea9cb43aa7c20f366e7e84e0d624414baf23defb0f12e83e2917ab3aaa7ed63"),
    "rogue_1_relic_r26": (12, "0f26e97c09d9668d65352847a1a410c8fb6cd6630257337e28e6e433ba2662f6"),
    "rogue_1_relic_r27": (12, "e536bb48f627ea60c1c94a6f2d9157763af5e0bdf3f084118ba5a91f113cdba3"),
    "rogue_1_relic_r28": (None, "3d46cd2bcd5dafa240a3c4a0a1f6923124d8dfb58641b36513e467dd5fffec70"),
    "rogue_1_relic_r13": (None, "6be97d2fffef82e923c12f2c3c77b37ef065d102defe087a49c51cd54f3d52c2"),
    "rogue_1_relic_q28": (16, "20e7b5804233977a770624be57adc35f4e4577ec6398f779d964c0fbd33034c0"),
})


def invalid():
    return ValueError("首主题正常商店资格或基础报价未匹配已核对规则")


@dataclass(frozen=True)
class MerchantRelic:
    id: str
    price: int | None
    opens_at: int


class FirstThemeMerchantRelics:
    """Compile terms only from trusted server-owned run/collection inputs."""

    def __init__(self, data):
        data.rogue_topics.topic("rogue_1")
        entries = {}
        try:
            detail = data.table("roguelike_topic_table")["details"]["rogue_1"]
            for key, (price, expected) in SOURCES.items():
                if key not in detail["items"]:
                    continue
                item = detail["items"][key]
                identity = {field: item[field] for field in ("id", "type", "iconId", "rarity", "unlockCondDesc")}
                archive = detail["archiveComp"]["relic"]["relic"][key]
                if (identity["id"] != key or identity["type"] != "RELIC"
                        or fingerprint({"item": identity, "archive": archive}) != expected):
                    raise invalid()
                ref = data.rogue_relic_archive.entries[key]
                if ref.special or ref.enrollment != archive["enrollId"]:
                    raise invalid()
                if key in FILTERS:
                    if key not in data.rogue_recruit_costs.modifiers:
                        raise invalid()
                elif key in CAPACITY_RELICS:
                    data.rogue_capacity_relics.require(key)
                elif key in GOLD_RELICS:
                    data.rogue_gold_relics.require(key)
                elif key in RESOURCE_RELICS:
                    data.rogue_resource_relics.require(key)
                else:
                    data.rogue_battle_attributes.require(key)
                at = 0
                if ref.enrollment is not None:
                    enroll = detail["enrolls"][ref.enrollment]
                    at = enroll["enrollTime"]
                    if (enroll["enrollId"] != ref.enrollment or type(at) is not int
                            or not 0 <= at < 2**63):
                        raise invalid()
                entries[key] = MerchantRelic(key, price, at)
        except (KeyError, TypeError, AttributeError) as exc:
            raise invalid() from exc
        self.data = data
        self.entries = MappingProxyType(entries)
        self.fingerprint = fingerprint({"policy": POLICY, "data": data.manifest["hash"],
            "sources": {key: SOURCES[key] for key in entries},
            "openings": {key: value.opens_at for key, value in entries.items()}})

    def offer(self, index, key, *, topic, mode, grade, at, collection_state, owned):
        identifier(index, "商品索引")
        if (topic != "rogue_1" or mode != "NORMAL" or type(grade) is not int or grade != 0
                or type(at) is not int or not 0 <= at < 2**63
                or type(collection_state) is not int or collection_state not in (1, 2)
                or type(owned) is not bool or owned or type(key) is not str):
            raise invalid()
        row = self.entries.get(key)
        if row is None or row.price is None or at < row.opens_at:
            raise invalid()
        return Offer(index, key, row.price, relic_layer=0)

    def compile(self, shop_id, slots, *, topic, mode, grade, at, collection, owned):
        """Bind an explicit selection to base terms, never choose a random pool.

        A run driver must supply its validated collection projection and owned
        relic IDs at plan creation. This does not authorize client-submitted
        eligibility and cannot retroactively reprice any persisted old quote.
        """
        if (type(slots) is not tuple or not 1 <= len(slots) <= 32
                or not isinstance(collection, Mapping) or type(owned) is not frozenset
                or any(type(key) is not str for key in owned)):
            raise invalid()
        offers, eligibility = [], {}
        for slot in slots:
            if (type(slot) is not tuple or len(slot) != 2
                    or any(type(value) is not str for value in slot)):
                raise invalid()
            index, key = slot
            state = collection.get(key)
            if not isinstance(state, Mapping):
                raise invalid()
            value = state.get("state")
            offers.append(self.offer(index, key, topic=topic, mode=mode, grade=grade, at=at,
                                     collection_state=value, owned=key in owned))
            eligibility[key] = value
        digest = fingerprint({"rules": self.fingerprint, "topic": topic, "mode": mode,
                              "grade": grade, "at": at, "collection": eligibility})
        return compile_shop(self.data, shop_id, tuple(offers),
                            evidence=POLICY + "; source=" + SOURCE + "; scope=" + digest)
