"""Causal cost history from owned node grants and their pending-ticket barrier.

This adapter admits one copy of compiled cost or battle-only effects.
Layer is supplied by the saved quote, never inferred from acquisition floor.
"""

from dataclasses import dataclass

from terralocal.server.domain.rogue_cost_history import (
    AcquireCostRelic,
    OpenRecruitOffer,
    RecruitCostHistory,
)
from terralocal.server.gamedata.rogue_battle_effects import SOURCES, supported
from terralocal.server.gamedata.rogue_capacity_relics import SOURCES as CAPACITY_SOURCES
from terralocal.server.gamedata.rogue_capacity_relics import supported as capacity_supported
from terralocal.server.gamedata.rogue_currency_relics import SOURCES as CURRENCY_SOURCES
from terralocal.server.gamedata.rogue_currency_relics import increase
from terralocal.server.gamedata.rogue_currency_relics import supported as currency_supported
from terralocal.server.gamedata.rogue_gold_relics import SOURCES as GOLD_SOURCES
from terralocal.server.gamedata.rogue_gold_relics import supported as gold_supported
from terralocal.server.gamedata.rogue_life_relics import SOURCES as LIFE_SOURCES
from terralocal.server.gamedata.rogue_life_relics import supported as life_supported
from terralocal.server.gamedata.rogue_resource_relics import SOURCES as RESOURCE_SOURCES
from terralocal.server.gamedata.rogue_resource_relics import supported as resource_supported

MAX_RELICS = (4 + len(SOURCES) + len(CAPACITY_SOURCES) + len(GOLD_SOURCES) + len(RESOURCE_SOURCES)
              + len(CURRENCY_SOURCES) + len(LIFE_SOURCES))


def admitted(data, key):
    return (key in data.rogue_recruit_costs.modifiers or supported(data, key)
            or capacity_supported(data, key) or gold_supported(data, key) or resource_supported(data, key)
            or currency_supported(data, key) or life_supported(data, key))


def resources_after_relic(data, key, state, *, credit_gold=True):
    """Shared transaction/replay consequence; shop gold already includes gains."""
    from terralocal.server.gamedata.rogue_battle_loot import gold_after_relic

    after = state.copy()
    if credit_gold:
        after["gold"] = gold_after_relic(data, key, state["gold"])
    if capacity_supported(data, key):
        after["squad_capacity"] = data.rogue_capacity_relics.increase(key, state["squad_capacity"])
    elif currency_supported(data, key):
        gain = data.rogue_currency_relics.require(key)
        after["hope_max"] = increase(state["hope_max"], gain.hope)
        after["squad_capacity"] = increase(state["squad_capacity"], gain.capacity)
    elif life_supported(data, key):
        after["hp"], after["hope_max"] = data.rogue_life_relics.apply(
            key, state["hp"], state["hp_max"], state["hope_max"])
    return after


@dataclass(frozen=True)
class RelicGrant:
    ordinal: int
    item_id: str
    layer: int
    at: int


class Progress(dict):
    """Out-of-band validation facts; legacy property JSON stays identical."""

    def __init__(self, values, grants, history, capacity_peak):
        super().__init__(values)
        self.relic_grants = tuple(grants)
        self.cost_history = history
        self.capacity_peak = capacity_peak


class Replay:
    def __init__(self, data, tickets):
        if (any(type(t.ordinal) is not int or t.ordinal < 0 for t in tickets)
                or len({t.ordinal for t in tickets}) != len(tickets)):
            raise ValueError("费用历史中的招募券序号不一致")
        self.data = data
        self.tickets = {t.ordinal: t for t in tickets}
        self.issued = {t.ordinal for t in tickets if t.ordinal < 3}
        self.events = [OpenRecruitOffer(i) for i in sorted(self.issued) if self.tickets[i].state != "CREATE"]
        self.grants = []
        self.capacity_peak = 0

    def capacity(self, value):
        if type(value) is not int or not 0 <= value < 2**31:
            raise ValueError("已回放容量历史非法")
        self.capacity_peak = max(self.capacity_peak, value)

    def ticket(self, ordinal):
        if ordinal in self.issued or ordinal not in self.tickets:
            raise ValueError("费用历史中的招募券发放不一致")
        self.issued.add(ordinal)
        if self.tickets[ordinal].state != "CREATE":
            self.events.append(OpenRecruitOffer(ordinal))

    def relic(self, offer, at):
        # Every earlier ticket must be resolved before buying another stock
        # slot or leaving its node. Thus no relic can intervene between that
        # ticket's grant and its candidate generation. This is causal replay,
        # not a comparison of same-second timestamps or today's inventory.
        if (any(self.tickets[i].state != "DONE" for i in self.issued)
                or offer.relic_layer != 0 or type(offer.relic_layer) is not int
                or not admitted(self.data, offer.item_id)
                or offer.item_id in {g.item_id for g in self.grants}):
            raise ValueError("收藏品发放或招募完成屏障不一致")
        self.grants.append(RelicGrant(len(self.grants) + 1, offer.item_id, offer.relic_layer, at))
        if offer.item_id in self.data.rogue_recruit_costs.modifiers:
            self.events.append(AcquireCostRelic(offer.item_id))

    def finish(self, values):
        # The recruit activation boundary expects a validated context once any
        # relic exists. Battle-only acquisitions contribute no cost event;
        # this still yields an empty modifier set with unchanged base prices.
        history = RecruitCostHistory(self.data.rogue_recruit_costs, tuple(self.events)) if self.grants else None
        return Progress(values, self.grants, history, self.capacity_peak)
