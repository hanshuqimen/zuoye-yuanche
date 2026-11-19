"""Versioned, pure replay of interleaved first-theme shop and bank payments.

This is an internal transaction prerequisite, not a live banking adapter. A
trusted plan must explicitly supply availability, withdrawal costs and each
successful deposit's post-credit fault outcome. No encounter/fault probability
or failed-deposit debit is inferred here. Callers must authenticate the account,
run and node, journal and grant atomically, and validate reward ownership.
"""

import re
import uuid
from dataclasses import asdict, dataclass, fields, replace

from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_shop import Purchase
from terralocal.server.domain.rogue_shop import replay as purchase_replay
from terralocal.server.gamedata.repository import fingerprint

POLICY = "rogue1-explicit-bank-shop-ledger-v1"
MAX_ACTIONS = 4096  # Explicit local journal budget, not an official visit limit.
KEY = re.compile(r"[A-Za-z0-9_.:/-]{1,160}")
HASH = re.compile(r"[0-9a-f]{64}")
KINDS = frozenset({"BUY", "PUT", "WITHDRAW", "LEAVE"})


def invalid():
    return DomainError("ROGUE_BANK_LEDGER_INCOMPATIBLE", "银行与商店支付记录不一致；请保留原存档", 503)


@dataclass(frozen=True)
class Terms:
    policy: str
    rules_hash: str
    quote_hash: str
    bank_open: bool
    allow_deposit: bool
    allow_withdraw: bool
    withdrawal_costs: tuple[int, ...]
    evidence: str

    @property
    def digest(self):
        return fingerprint(asdict(self))


def compile_terms(data, shop, *, mode, grade, bank_open, allow_deposit, allow_withdraw,
                  withdrawal_costs, evidence):
    """Admit an explicit owned plan; never use default zero table values.

    The last supplied withdrawal cost repeats. Supplying these terms is not
    evidence of official stock generation, rewards, opening or probabilities.
    """
    rules = data.rogue_bank
    if (type(mode) is not str or mode != "NORMAL" or type(grade) is not int or grade != 0
            or shop.data_hash != data.manifest["hash"] or shop.gold_id != rules.gold
            or any(type(v) is not bool for v in (bank_open, allow_deposit, allow_withdraw))
            or not bank_open and (allow_deposit or allow_withdraw)
            or type(withdrawal_costs) is not tuple or not 1 <= len(withdrawal_costs) <= 32
            or any(type(v) is not int or not 1 <= v < 2**31 for v in withdrawal_costs)
            or type(evidence) is not str or not 1 <= len(evidence) <= 1024):
        raise invalid()
    return Terms(POLICY, rules.fingerprint, shop.digest, bank_open, allow_deposit,
                 allow_withdraw, withdrawal_costs, evidence)


@dataclass(frozen=True)
class Action:
    key: str
    kind: str
    at: int
    index: str | None = None
    ticket: int | None = None
    fault_after: bool | None = None


@dataclass(frozen=True)
class Journal:
    policy: str
    binding_hash: str
    actions: tuple[Action, ...] = ()


@dataclass(frozen=True)
class Scope:
    account_id: int
    run_id: str
    visit_id: str


@dataclass(frozen=True)
class State:
    gold: int
    current: int
    record: int
    total_put: int
    faulty: bool
    withdrawals: int = 0
    purchases: tuple[Purchase, ...] = ()
    ended_at: int | None = None

    def bank_snapshot(self, initial):
        # Retain claimed keys verbatim; crossing a threshold cannot earn one.
        return dict(initial) | {"reward": dict(initial["reward"]), "current": self.current,
                                "record": self.record, "totalPut": self.total_put}


def binding(rules, shop, terms, bank, gold, entered_at, first_ticket, scope, faulted_before):
    bank = rules.validate_bank(bank)
    if (type(scope) is not Scope or type(scope.account_id) is not int or not 0 < scope.account_id < 2**63
            or any(type(value) is not str or str(uuid.UUID(value)) != value
                   for value in (scope.run_id, scope.visit_id))):
        raise invalid()
    if (bank is None or type(terms) is not Terms or terms.policy != POLICY
            or terms.rules_hash != rules.fingerprint or terms.quote_hash != shop.digest
            or shop.gold_id != rules.gold
            or any(type(v) is not bool for v in (terms.bank_open, terms.allow_deposit, terms.allow_withdraw))
            or not terms.bank_open and (terms.allow_deposit or terms.allow_withdraw)
            or type(terms.withdrawal_costs) is not tuple or not 1 <= len(terms.withdrawal_costs) <= 32
            or any(type(v) is not int or not 1 <= v < 2**31 for v in terms.withdrawal_costs)
            or type(terms.evidence) is not str or not 1 <= len(terms.evidence) <= 1024
            or type(gold) is not int or not 0 <= gold < 2**31
            or type(entered_at) is not int or not 0 <= entered_at < 2**63
            or type(first_ticket) is not int or not 3 <= first_ticket < 2**31
            or type(faulted_before) is not bool):
        raise invalid()
    # Preserve old payment validation, including ticket classification.
    purchase_replay(shop, gold, entered_at, first_ticket, ())
    return fingerprint({"policy": POLICY, "rules": rules.fingerprint, "quote": shop.digest,
        "terms": terms.digest, "bank": bank, "gold": gold, "entered": entered_at,
        "first_ticket": first_ticket, "scope": asdict(scope), "faulted_before": faulted_before})


def begin(rules, shop, terms, bank, gold, entered_at, first_ticket, scope, *, faulted_before):
    try:
        return Journal(POLICY, binding(rules, shop, terms, bank, gold, entered_at, first_ticket, scope, faulted_before))
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise invalid() from exc


def validate_action(action):
    if (type(action) is not Action or type(action.key) is not str or not KEY.fullmatch(action.key)
            or type(action.kind) is not str or action.kind not in KINDS
            or type(action.at) is not int or not 0 <= action.at < 2**63
            or action.kind == "BUY" and (type(action.index) is not str or not 1 <= len(action.index) <= 128)
            or action.kind != "BUY" and (action.index is not None or action.ticket is not None)
            or action.kind == "PUT" and type(action.fault_after) is not bool
            or action.kind != "PUT" and action.fault_after is not None):
        raise invalid()


def withdrawal_cost(terms, completed):
    return terms.withdrawal_costs[min(completed, len(terms.withdrawal_costs) - 1)]


def apply(rules, shop, terms, bank, state, action, first_ticket):
    """Apply one validated, server-authored action in ordinal order."""
    if action.kind == "LEAVE":
        return replace(state, ended_at=action.at)
    if action.kind == "BUY":
        if any(p.index == action.index for p in state.purchases):
            raise invalid()  # A retry must reuse its receipt, never append stock twice.
        if action.index not in shop.offers:
            raise DomainError("ROGUE_SHOP_GOOD", "商品不属于此商店")
        if shop.offers[action.index].price > state.gold:
            raise DomainError("ROGUE_SHOP_GOLD", "源石锭不足，未购买商品", 409)
        ticket = first_ticket + sum(p.ticket is not None for p in state.purchases)
        purchase = Purchase(action.index, action.at, action.ticket)
        paid = purchase_replay(shop, state.gold, action.at, ticket, (purchase,))
        return replace(state, gold=paid.gold, purchases=state.purchases + (purchase,))
    if not terms.bank_open or not bank["show"]:
        raise DomainError("ROGUE_BANK_CLOSED", "当前商店银行未开放", 409)
    if action.kind == "PUT":
        if not terms.allow_deposit or state.faulty:
            raise DomainError("ROGUE_BANK_PUT_UNAVAILABLE", "当前探索不能继续投资", 409)
        if state.gold < 1:
            raise DomainError("ROGUE_BANK_GOLD", "源石锭不足，未投资", 409)
        if state.current >= rules.maximum or state.total_put >= 2**31 - 1:
            raise DomainError("ROGUE_BANK_FULL", "投资余额或累计记录达到上限，未扣款", 409)
        return replace(state, gold=state.gold - 1, current=state.current + 1,
                       record=max(state.record, state.current + 1), total_put=state.total_put + 1,
                       faulty=action.fault_after)
    # Authorization is an explicit trusted input. ContainsKey was observed in
    # slot/notice consumers, not as proof of bank withdrawal entitlement.
    # The persistent adapter must verify the entitlement's actual source.
    if not terms.allow_withdraw:
        raise DomainError("ROGUE_BANK_WITHDRAW_LOCKED", "当前商店取款未解锁", 409)
    cost = withdrawal_cost(terms, state.withdrawals)
    if state.current < cost:
        raise DomainError("ROGUE_BANK_BALANCE", "投资余额不足，未取款", 409)
    if state.gold >= 2**31 - 1:
        raise DomainError("ROGUE_BANK_GOLD_LIMIT", "源石锭达到上限，未扣除投资余额", 409)
    return replace(state, gold=state.gold + 1, current=state.current - cost, withdrawals=state.withdrawals + 1)


def replay(rules, shop, terms, bank, gold, entered_at, first_ticket, scope, journal, *, faulted_before):
    """Reject changed bindings, duplicate keys, unpaid stock and time disorder."""
    try:
        expected = binding(rules, shop, terms, bank, gold, entered_at, first_ticket, scope, faulted_before)
        if (type(journal) is not Journal or journal.policy != POLICY or journal.binding_hash != expected
                or type(journal.actions) is not tuple or len(journal.actions) > MAX_ACTIONS):
            raise invalid()
        state = State(gold, bank["current"], bank["record"], bank["totalPut"], faulted_before)
        keys, boundary = set(), entered_at
        for action in journal.actions:
            validate_action(action)
            if action.key in keys or action.at < boundary or state.ended_at is not None:
                raise invalid()
            keys.add(action.key)
            state = apply(rules, shop, terms, bank, state, action, first_ticket)
            boundary = action.at
        return state
    except (DomainError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise invalid() from exc


def decide(rules, shop, terms, bank, gold, entered_at, first_ticket, scope, journal, *, faulted_before,
           key, kind, at, index=None, fault_after=None, recruit_pending=False):
    """Return a new journal and state; same scoped key replays, new key acts.

    The outer adapter must derive keys from its authenticated session/sequence
    receipt. Empty request bodies alone are never deposit idempotency keys.
    The fault outcome is mandatory for PUT, must be chosen by trusted code, and
    is not rerolled for a committed key. This API grants no item or database write.
    """
    state = replay(rules, shop, terms, bank, gold, entered_at, first_ticket, scope, journal,
                   faulted_before=faulted_before)
    boundary = journal.actions[-1].at if journal.actions else entered_at
    if type(at) is not int or not 0 <= at < 2**63 or type(recruit_pending) is not bool:
        raise DomainError("ROGUE_BANK_ACTION", "银行操作格式无效")
    validate_action(Action(key, kind, max(at, boundary), index, None, fault_after))
    ticket = (first_ticket + sum(p.ticket is not None for p in state.purchases)
              if kind == "BUY" and index in shop.ticket_indices else None)
    action = Action(key, kind, max(at, boundary), index, ticket, fault_after)
    validate_action(action)
    old = next((a for a in journal.actions if a.key == key), None)
    if old:
        if (old.kind, old.index) != (kind, index):
            raise DomainError("IDEMPOTENCY_CONFLICT", "相同操作编号不能用于不同交易", 409)
        return journal, state
    if kind == "LEAVE" and state.ended_at is not None:
        return journal, state
    if state.ended_at is not None:
        raise DomainError("ROGUE_BANK_VISIT_CLOSED", "已经离开此商店", 409)
    if kind == "BUY" and any(p.index == index for p in state.purchases):
        return journal, state  # Preserve existing one-stock new-sequence retry behavior.
    if recruit_pending:
        raise DomainError("ROGUE_RECRUIT_PENDING", "请先处理当前招募", 409)
    if len(journal.actions) >= MAX_ACTIONS:
        raise DomainError("ROGUE_BANK_JOURNAL_LIMIT", "达到本地交易记录预算；未扣款或发奖", 503)
    updated = apply(rules, shop, terms, bank, state, action, first_ticket)
    return replace(journal, actions=journal.actions + (action,)), updated


def dump(journal):
    return {"policy": journal.policy, "binding_hash": journal.binding_hash,
            "actions": [asdict(a) for a in journal.actions]}


def load(value):
    """Strict owned save format; replay still verifies financial/source facts."""
    try:
        if (type(value) is not dict or set(value) != {"policy", "binding_hash", "actions"}
                or value["policy"] != POLICY or type(value["binding_hash"]) is not str
                or not HASH.fullmatch(value["binding_hash"]) or type(value["actions"]) is not list
                or len(value["actions"]) > MAX_ACTIONS):
            raise invalid()
        actions = []
        for row in value["actions"]:
            if type(row) is not dict or set(row) != {f.name for f in fields(Action)}:
                raise invalid()
            action = Action(**row)
            validate_action(action)
            actions.append(action)
        return Journal(value["policy"], value["binding_hash"], tuple(actions))
    except (DomainError, TypeError, ValueError, KeyError) as exc:
        raise invalid() from exc
