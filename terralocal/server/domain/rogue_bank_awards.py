"""First-theme bank reward keys at a verified exploration settlement boundary.

PRTS describes effects starting after settlement. Frozen M133354 distinguishes
key membership from reaching a threshold; M154202 tracks newly added keys.
The opaque value 1 follows the reviewed public DoctorateTs bank template; this
is a versioned local compatibility convention, not proof of official values.
No threshold observation or client request is an award authority by itself.
"""

import re
import uuid

from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.repository import canonical, fingerprint

POLICY = "rogue1-settled-bank-rewards-marker1-v1"
MARKER = 1
FIELDS = frozenset({"policy", "rules", "account", "run", "data", "score", "at", "visits", "head", "before", "rewards"})
HEX = re.compile(r"[0-9a-f]{64}")


def invalid():
    return DomainError("ROGUE_BANK_AWARD_INCOMPATIBLE", "投资奖赏与探索结算来源不一致；请保留原存档", 503)


def pending(rules, bank):
    bank = rules.validate_bank(bank)
    if bank is None:
        return ()
    return tuple(sorted(key for key, row in rules.rewards.items()
                        if key not in bank["reward"] and row.threshold <= rules.accumulated(bank)))


def event(rules, bank, run, settlement, *, visits, head):
    """Bind all newly reached keys to one owned, confirmed settlement.

    Callers must load the run/result from trusted persistence, verify the whole
    score ledger, and prove this run owns the last closed bank visit. No random
    sampling, natural opening or item distribution is admitted by this kernel.
    """
    try:
        bank = rules.validate_bank(bank)
        if (bank is None or rules.counter != "HIGHEST_RECORD" or run.topic_id != "rogue_1"
                or run.mode != "NORMAL" or type(run.grade) is not int or run.grade != 0
                or run.state != "SETTLED" or type(run.account_id) is not int or not 0 < run.account_id < 2**63
                or type(run.id) is not str or str(uuid.UUID(run.id)) != run.id
                or settlement is None or settlement.run_id != run.id
                or type(run.gamedata_hash) is not str or not HEX.fullmatch(run.gamedata_hash)
                or run.gamedata_hash != rules.data_hash
                or type(settlement.rule_hash) is not str or not HEX.fullmatch(settlement.rule_hash)
                or any(type(v) is not int or not 0 <= v < 2**63
                       for v in (run.created_at, run.ended_at, settlement.created_at))
                or not run.created_at <= run.ended_at <= settlement.created_at
                or type(visits) is not int or not 1 <= visits < 2**31
                or type(head) is not str or not HEX.fullmatch(head)):
            raise invalid()
        rewards = pending(rules, bank)
        if not rewards:
            return None
        return {"policy": POLICY, "rules": rules.fingerprint, "account": run.account_id,
                "run": run.id, "data": run.gamedata_hash, "score": settlement.rule_hash,
                "at": settlement.created_at, "visits": visits, "head": head,
                "before": fingerprint(bank), "rewards": list(rewards)}
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise invalid() from exc


def load(rules, log):
    if (type(log) is not list or len(log) > len(rules.rewards)
            or any(type(row) is not dict or set(row) != FIELDS for row in log)):
        raise invalid()
    previous = 0
    runs = set()
    for row in log:
        if (type(row["visits"]) is not int or not previous < row["visits"] < 2**31
                or type(row["run"]) is not str or row["run"] in runs):
            raise invalid()
        previous = row["visits"]
        runs.add(row["run"])
    return log


def apply(rules, bank, row, run, settlement, *, visits, head):
    expected = event(rules, bank, run, settlement, visits=visits, head=head)
    if expected is None or canonical(row) != canonical(expected):
        raise invalid()
    return dict(bank) | {"reward": dict(bank["reward"]) | {key: MARKER for key in expected["rewards"]}}
