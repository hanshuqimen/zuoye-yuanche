"""First-theme bank terms and native shop-slot projection.

M33695 checks reward-key membership, not its value or the current balance.
M33696 distinguishes the highest record from cumulative deposits. M155060
shows a new-reward notice only at an exact threshold with an absent key. These
are read-only consumers, not proof of a deposit, a claimed reward, a natural stock
size, a failure probability or an implemented banking transaction.
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.gamedata.roguelike import identifier

POLICY = "rogue1-bank-native-slot-terms-v1"
REWARD_TYPES = frozenset({"ADD_SHOP_POS", "UNLOCK_ITEM", "UNLOCK_WITHDRAW"})
COUNT_TYPES = frozenset({"HIGHEST_RECORD", "TOTAL_SUM"})
BANK_FIELDS = frozenset({"show", "current", "record", "totalPut", "reward"})


def invalid():
    return ValueError("首主题投资规则或保存状态未匹配；未生成商品或发放奖励")


@dataclass(frozen=True)
class BankReward:
    id: str
    kind: str
    threshold: int


class FirstThemeBankRules:
    def __init__(self, data):
        data.rogue_topics.topic("rogue_1")
        try:
            detail = data.table("roguelike_topic_table")["details"]["rogue_1"]
            const = detail["gameConst"]
            gold, maximum, counter = (const[k] for k in ("goldItemId", "bankMaxGold", "bankRewardCountType"))
            identifier(gold, "投资货币")
            item = detail["items"][gold]
            if (item["id"] != gold or item["type"] != "GOLD" or type(maximum) is not int
                    or not 1 <= maximum < 2**31 or type(counter) is not str or counter not in COUNT_TYPES):
                raise invalid()
            rows = detail["bankRewards"]
            if type(rows) is not list or not 1 <= len(rows) <= 64:
                raise invalid()
            rewards = {}
            for row in rows:
                if type(row) is not dict:
                    raise invalid()
                key, kind, threshold = (row[k] for k in ("rewardId", "rewardType", "unlockGoldCnt"))
                identifier(key, "投资奖励")
                if (key in rewards or type(kind) is not str or kind not in REWARD_TYPES
                        or type(threshold) is not int or not 1 <= threshold < 2**31):
                    raise invalid()
                # A cumulative-deposit threshold may legitimately exceed the
                # balance cap; a highest-balance threshold cannot.
                if counter == "HIGHEST_RECORD" and threshold > maximum:
                    raise invalid()
                rewards[key] = BankReward(key, kind, threshold)
        except (KeyError, TypeError, AttributeError) as exc:
            raise invalid() from exc
        self.gold, self.maximum, self.counter = gold, maximum, counter
        self.data_hash = data.manifest["hash"]
        self.rewards = MappingProxyType(rewards)
        self.slot_rewards = frozenset(key for key, row in rewards.items() if row.kind == "ADD_SHOP_POS")
        self.fingerprint = fingerprint({"policy": POLICY, "data": data.manifest["hash"],
            "gold": gold, "maximum": maximum, "counter": counter,
            "rewards": [(r.id, r.kind, r.threshold) for r in rewards.values()]})

    def validate_bank(self, bank):
        """Validate an explicit owned snapshot; never fill absent balances."""
        if bank is None:
            return None  # Native GetRoguelikeTopicBankData may return null.
        if (not isinstance(bank, Mapping) or set(bank) != BANK_FIELDS or type(bank["show"]) is not bool
                or any(type(bank[k]) is not int or not 0 <= bank[k] < 2**31
                       for k in ("current", "record", "totalPut"))
                or not bank["current"] <= bank["record"] <= self.maximum
                or bank["totalPut"] < bank["record"] or not isinstance(bank["reward"], Mapping)
                or any(type(k) is not str or k not in self.rewards or type(v) is not int or not 0 <= v < 2**31
                       for k, v in bank["reward"].items())):
            raise invalid()
        return bank

    def accumulated(self, bank):
        bank = self.validate_bank(bank)
        return 0 if bank is None else bank["totalPut" if self.counter == "TOTAL_SUM" else "record"]

    def has_new_reward(self, bank):
        """Mirror M155060's default notice predicate; never grant a reward.

        Equality and key membership are both intentional. A higher record does
        not reproduce this notice for an earlier, absent reward; a present key
        with value zero suppresses it. No show/boss/mode gate exists in this
        consumer itself. Callers still own context and transaction validation.
        """
        bank = self.validate_bank(bank)
        if bank is None:
            return False  # All admitted table thresholds are strictly positive.
        count = self.accumulated(bank)
        return any(count == reward.threshold and key not in bank["reward"]
                   for key, reward in self.rewards.items())

    def locked_slots(self, bank, *, normal_mode, has_boss):
        """Mirror M33695; callers supply the validated native mode predicate.

        Presence is intentional: a saved key with integer zero still satisfies
        ContainsKey. This function neither authenticates a reward claim nor
        turns thresholds into newly claimed keys. It never mutates the snapshot.
        """
        if type(normal_mode) is not bool or type(has_boss) is not bool:
            raise invalid()
        bank = self.validate_bank(bank)
        if not normal_mode or not has_boss or bank is None or not bank["show"]:
            return 0
        return len(self.slot_rewards - bank["reward"].keys())
