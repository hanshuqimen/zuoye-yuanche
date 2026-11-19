"""Version-bound ordinary capsule effects; no natural offer/drop policy."""

from dataclasses import dataclass

from terralocal.server.gamedata.repository import fingerprint

SOURCES = {
    "rogue_1_capsule_9": (
        "5eb9de3c4d9050b9e8448164ff5c04b6821bfa739e8d8cd9c9c666f1eb392a38",
        "bf3d1dd1445983ce2764f41ba8911ca654b06d1dc54a656ea525830025ae279e", 1, 0),
    "rogue_1_capsule_10": (
        "ae08b4bee4f9ab59d2c0262ab58a6879dfbef422d349b07eb965f85c4c8f26f7",
        "d8db23474e938ccf2d3a952ddb9cee6c4fc43f908c9708396f946a11910d44fa", 0, 3),
}
EXP_SOURCES = {
    "rogue_1_capsule_3": (
        "2d2442cac2bf433652509b5639d044e2535e498296a724d548ca79ebf28aa360",
        "0dafbba7e1d6dffc21e3bc00ccf4275026d8c27fc2c32ad15595c7dcb765b60d"),
}


@dataclass(frozen=True)
class Capsule:
    id: str
    mask: str
    hp: int
    gold: int
    digest: str
    exp_multiplier: int = 1

    def matches(self, kind):
        return kind in ("BATTLE_NORMAL", "BATTLE_ELITE", "BATTLE_BOSS") if self.mask == "BATTLES" else kind == self.mask


def require(data, key, *, at):
    """Check the entire referenced definition, not a parsed usage expression."""
    if type(key) is not str or key not in SOURCES.keys() | EXP_SOURCES.keys() or type(at) is not int or not 0 <= at < 2**63:
        raise ValueError("剧目效果尚未接通，或缺少匹配的明确来源")
    data.rogue_topics.topic("rogue_1", at=at)
    detail = data.table("roguelike_topic_table")["details"]["rogue_1"]
    item, capsule = detail["items"].get(key), detail.get("capsuleDict", {}).get(key)
    mask, multiplier = ("BATTLES", 2) if key in EXP_SOURCES else ("INCIDENT", 1)
    expected_item, expected_capsule, hp, gold = (*EXP_SOURCES[key], 0, 0) if key in EXP_SOURCES else SOURCES[key]
    if (fingerprint(item) != expected_item or fingerprint(capsule) != expected_capsule
            or item["type"] != "CAPSULE" or item["subType"] != "NONE"
            or capsule["itemId"] != key or capsule["maskType"] != mask):
        raise ValueError("剧目物品、节点类别或完整效果定义不匹配")
    proof = [data.manifest["hash"], at, item, capsule, hp, gold]
    if multiplier != 1:
        proof.append({"battle_exp_multiplier": multiplier})
    return Capsule(key, mask, hp, gold, fingerprint(proof), multiplier)


def available(data):
    if data is None or "roguelike_topic_table" not in data.manifest["tables"]:
        return False
    details = data.table("roguelike_topic_table")["details"]
    return bool((SOURCES.keys() | EXP_SOURCES.keys()) & details.get("rogue_1", {}).get("capsuleDict", {}).keys())
