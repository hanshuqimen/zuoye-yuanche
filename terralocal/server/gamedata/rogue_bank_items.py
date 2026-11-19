"""Two exact bank reward/item bindings; no unlock-prose parser or wire guess.

Bank rewards carry a display description rather than a structured item ID.
Keep the reviewed binding explicit and bind the full row and item identity.
Eligibility requires a verified settled reward event in a subsequent run.
"""

from dataclasses import dataclass
from types import MappingProxyType

from terralocal.server.gamedata.repository import fingerprint

POLICY = "rogue1-settled-bank-item-bindings-v1"
PROJECTION_POLICY = "rogue1-replayed-bank-archive-progress-v1"
SOURCES = MappingProxyType({
    "rogue_1_relic_r13": ("bank_reward_2", 100, "无瑕宝玉",
        "6be97d2fffef82e923c12f2c3c77b37ef065d102defe087a49c51cd54f3d52c2"),
    "rogue_1_relic_q28": ("bank_reward_4", 325, "金酒之杯",
        "20e7b5804233977a770624be57adc35f4e4577ec6398f779d964c0fbd33034c0"),
})


def invalid():
    return ValueError("首主题银行收藏品奖励绑定与完整匹配数据不一致")


def available(data):
    if data is None or "roguelike_topic_table" not in data.manifest["tables"]:
        return False
    detail = data.table("roguelike_topic_table")["details"].get("rogue_1", {})
    rewards = {row[0] for row in SOURCES.values()}
    rows = detail.get("bankRewards", [])
    return (type(rows) is list and any(type(row) is dict and row.get("rewardId") in rewards for row in rows)
            or any(detail.get("items", {}).get(key, {}).get("unlockCondDesc") ==
                   f"在“前瞻性投资系统”中的投资储备余额最高达到过{row[1]}" for key, row in SOURCES.items()))


@dataclass(frozen=True)
class BankProgress:
    current: int
    target: int
    unlocked: bool
    known: bool

    def wire(self):
        # M154269 reads exactly two integers; M194808 reads state separately.
        # A reached threshold may still await confirmed exploration settlement.
        return {"state": int(self.unlocked), "progress": [self.current, self.target] if self.known else []}


class FirstThemeBankItems:
    def __init__(self, data):
        data.rogue_topics.topic("rogue_1")
        try:
            detail = data.table("roguelike_topic_table")["details"]["rogue_1"]
            rules = data.rogue_bank
            if rules.counter != "HIGHEST_RECORD":
                raise invalid()
            bindings, sources = {}, {}
            for key, (reward, threshold, name, expected) in SOURCES.items():
                item = detail["items"][key]
                identity = {f: item[f] for f in ("id", "type", "iconId", "rarity", "unlockCondDesc")}
                archive = detail["archiveComp"]["relic"]["relic"][key]
                ref = data.rogue_relic_archive.entries[key]
                rows = [row for row in detail["bankRewards"] if row["rewardId"] == reward]
                row = {"rewardId": reward, "rewardType": "UNLOCK_ITEM", "unlockGoldCnt": threshold,
                       "desc": "解锁收藏品【" + name + "】"}
                rule = rules.rewards[reward]
                if (identity["id"] != key or identity["type"] != "RELIC" or item["name"] != name
                        or identity["unlockCondDesc"] != f"在“前瞻性投资系统”中的投资储备余额最高达到过{threshold}"
                        or fingerprint({"item": identity, "archive": archive}) != expected
                        or ref.special or ref.enrollment is not None or rows != [row]
                        or rule.kind != "UNLOCK_ITEM" or rule.threshold != threshold):
                    raise invalid()
                bindings[key] = reward
                sources[key] = {"identity": expected, "reward": row}
        except (KeyError, TypeError, AttributeError) as exc:
            raise invalid() from exc
        self.bindings = MappingProxyType(bindings)
        self.rules = rules
        self.fingerprint = fingerprint({"policy": POLICY, "data": data.manifest["hash"],
                                        "bank": rules.fingerprint, "sources": sources})
        self.projection_fingerprint = fingerprint({"policy": PROJECTION_POLICY, "bindings": self.fingerprint,
            "counter": rules.counter, "availability": "settled_reward_membership", "unowned": "unknown_progress"})

    def evaluate_verified(self, bank):
        """Only an independently replayed wallet may supply these counters.

        None means unknown/unowned legacy history, not a zero balance claim.
        This is a local canonical projection of the recovered client fields,
        not an official server packet or an authority for merchant selection.
        """
        bank = self.rules.validate_bank(bank)
        current = 0 if bank is None else self.rules.accumulated(bank)
        return MappingProxyType({key: BankProgress(min(current, self.rules.rewards[reward].threshold),
            self.rules.rewards[reward].threshold, bank is not None and reward in bank["reward"], bank is not None)
            for key, reward in self.bindings.items()})
