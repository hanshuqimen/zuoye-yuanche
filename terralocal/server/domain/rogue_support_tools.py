"""Single owned tool derived from ordered, validated purchase receipts.

There is no independent editable inventory flag. Every replacement retains
its source visit/stock identity; retries of old purchases cannot re-equip it.
"""

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class ToolGrant:
    visit_id: str
    stock_index: str
    item_id: str
    at: int

    def wire(self):
        return {"id": self.item_id, "ts": self.at}


class ToolHistory:
    def __init__(self, data, run):
        self.data, self.run, self.grants = data, run, []
        self.battles = {}

    def acquire(self, visit, purchase, offer, *, recruit_pending=False):
        run = self.run
        if (run.topic_id != "rogue_1" or run.mode != "NORMAL" or run.grade != 0
                or type(purchase.at) is not int or not run.created_at <= purchase.at < 2**63
                or run.ended_at is not None and purchase.at > run.ended_at
                or self.grants and purchase.at < self.grants[-1].at
                or recruit_pending or purchase.ticket is not None or offer.relic_layer is not None
                or any((g.visit_id, g.stock_index) == (visit.id, purchase.index) for g in self.grants)):
            raise ValueError("支援道具的购买来源、顺序或招募完成屏障不一致")
        self.data.rogue_support_tools.require(offer.item_id, run.created_at)
        self.grants.append(ToolGrant(visit.id, purchase.index, offer.item_id, purchase.at))

    def bind_battle(self, battle):
        from terralocal.server.domain.rogue_battle import TOOL_POLICIES

        if battle.id in self.battles or battle.run_id != self.run.id:
            raise ValueError("工具战斗来源不属于当前探索或重复出现")
        grant = self.current
        if (grant is not None) != (battle.policy_version in TOOL_POLICIES):
            raise ValueError("工具战斗能力版本与按节点顺序确定的持有来源不匹配")
        if grant is not None:
            if (battle.account_id != self.run.account_id
                    or type(battle.started_at) is not int or grant.at > battle.started_at):
                raise ValueError("不能用未来获得的道具改写过去战斗")
            self.data.rogue_tool_effects.require(grant.item_id, self.run.created_at)
        self.battles[battle.id] = grant

    @property
    def battle_bindings(self):
        return MappingProxyType(self.battles.copy())

    @property
    def current(self):
        return self.grants[-1] if self.grants else None
