"""Ordered cost contexts, independent of acquisition adapters and wall clocks.

These events must come from an owned, replay-validated transaction history.
They are not a client request schema and do not authorize or grant a relic.
Only the four permanent, unconditional first-theme effects are admitted.
"""

from dataclasses import dataclass
from types import MappingProxyType

from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.gamedata.rogue_recruit_costs import FirstThemeRecruitCostRules

POLICY = "rogue1-recruit-offer-cost-context-v1"


@dataclass(frozen=True)
class AcquireCostRelic:
    item_id: str


@dataclass(frozen=True)
class OpenRecruitOffer:
    ticket: int


@dataclass(frozen=True)
class CostContext:
    ticket: int
    modifiers: tuple[str, ...]
    prefix_hash: str


def invalid():
    return ValueError("招募费用历史缺少明确且一致的交易顺序")


class RecruitCostHistory:
    """Freeze each offer when opened; later relics cannot rewrite its price.

    Input tuple order is authoritative, including same-second transactions.
    Opening means creation of immutable candidate offers, not merely granting
    an unopened ticket. Repeated requests belong in the transaction adapter;
    duplicate acquisition/open events here are corrupt history, not retries.
    Counts, layers, used/consumed effects and acquisition eligibility remain
    the responsibility of that adapter. Nothing in this class infers them.
    """

    def __init__(self, rules: FirstThemeRecruitCostRules, events):
        if (not isinstance(rules, FirstThemeRecruitCostRules) or type(events) is not tuple
                or len(events) > 263):  # Existing 259-ticket budget plus these four unique effects.
            raise invalid()
        owned, contexts = set(), {}
        prefix = fingerprint({"policy": POLICY, "rules": rules.fingerprint})
        for event in events:
            if type(event) is AcquireCostRelic:
                key = event.item_id
                if type(key) is not str or key not in rules.modifiers or key in owned:
                    raise invalid()
                owned.add(key)
                fact = {"acquire": key}
            elif type(event) is OpenRecruitOffer:
                number = event.ticket
                if (type(number) is not int or not 0 <= number < 2**31
                        or number in contexts or len(contexts) >= 259):
                    raise invalid()
                fact = {"open": number}
            else:
                raise invalid()
            prefix = fingerprint({"previous": prefix, "event": fact})
            if type(event) is OpenRecruitOffer:
                contexts[event.ticket] = CostContext(event.ticket, tuple(sorted(owned)), prefix)
        self.contexts = MappingProxyType(contexts)
        self.final_modifiers = tuple(sorted(owned))
        self.fingerprint = prefix
        self._rules = rules

    def context(self, ticket):
        if type(ticket) is not int or ticket not in self.contexts:
            raise invalid()
        return self.contexts[ticket]

    def quote(self, ticket, base, *, profession, rarity, operation="RECRUIT"):
        context = self.context(ticket)
        return self._rules.quote(base, profession=profession, rarity=rarity,
                                 modifiers=context.modifiers, operation=operation)
