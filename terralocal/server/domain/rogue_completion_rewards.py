"""Versioned first-theme completion notifications and ordered ending history.

Client list rendering is REA-verified. The 25-candle amount is the explicit
PRTS first-theme player rule, not the unrelated global relicTokenRatio field.
No item inventory or natural encounter pool is granted by this adapter.
"""

from collections import defaultdict

from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.gamedata.rogue_ending_unlocks import RunCompletion

POLICY = "rogue1-normal0-completion-unlocks-prts25-v7"
VARIANT_POLICY = "rogue1-normal0-conditional-completion-unlocks-prts25-v8"
DEPLOYMENT_POLICY = "rogue1-normal0-deployment-completion-unlocks-prts25-v9"
CAPACITY_POLICY = "rogue1-normal0-capacity-completion-unlocks-prts25-v10"
GIVEUP_POLICY = "rogue1-normal0-giveup-unlocks-prts25-v11"
CAPACITY_POLICIES = frozenset({CAPACITY_POLICY, GIVEUP_POLICY})
DEPLOYMENT_POLICIES = frozenset({DEPLOYMENT_POLICY, *CAPACITY_POLICIES})
VARIANT_POLICIES = frozenset({VARIANT_POLICY, *DEPLOYMENT_POLICIES})
ORDERED_POLICIES = frozenset({POLICY, *VARIANT_POLICIES})
REWARD_POLICY = "rogue1-completion-unlock-candles-prts25-v1"
SOURCE = "https://prts.wiki/w/傀影与猩红孤钻#长生者宝盒（收藏品一览）"
PER_ITEM = 25


def invalid():
    return DomainError("ROGUE_COMPLETION_REWARD_INCOMPATIBLE", "通关解锁结算或历史顺序不一致；请保留原存档", 503)


def ordered_groups(entries, legacy_policies):
    """Preserve old order; new rows have an explicit bounded predecessor link."""
    groups = defaultdict(list)
    seen = set()
    for run, row in entries:
        if row.run_id != run.id or run.id in seen:
            raise invalid()
        seen.add(run.id)
        groups[run.account_id, run.topic_id].append((run, row))
    result = {}
    for key, rows in groups.items():
        old = sorted((pair for pair in rows if pair[1].policy_version in legacy_policies),
                     key=lambda pair: (pair[0].created_at, pair[0].id))
        current = []
        for pair in rows:
            row = pair[1]
            if row.policy_version in legacy_policies:
                continue
            note = row.facts.get("notification")
            if (row.policy_version not in ORDERED_POLICIES or type(note) is not dict
                    or type(note.get("sequence")) is not int or not 0 <= note["sequence"] < 2**31):
                raise invalid()
            current.append(pair)
        current.sort(key=lambda pair: pair[1].facts["notification"]["sequence"])
        ordered = list(old)
        for run, row in current:
            note = row.facts["notification"]
            previous = {"run": ordered[-1][0].id, "hash": ordered[-1][1].rule_hash} if ordered else None
            if (note["sequence"] != len(ordered) or note.get("previous") != previous
                    or ordered and ordered[-1][1].after != row.before):
                raise invalid()
            ordered.append((run, row))
        result[key] = tuple(ordered)
    return result


def completion(run, known):
    return RunCompletion(run.mode, run.grade, run.created_at, known["ended"],
                         known.get("success", 0), known.get("ending"))


def notification(data, run, known, base_policy, prefix, *, policy=POLICY, attained=(), deployment_prefix=None,
                 capacity_scope=None):
    from terralocal.server.domain.rogue_giveup import SCORE_POLICY as GIVEUP_SCORE_POLICY
    from terralocal.server.domain.rogue_giveup import confirmed_state

    rules = data.rogue_ending_unlocks
    previous = []
    seen = set()
    for earlier, row in prefix:
        if (earlier.id == run.id or earlier.id in seen or earlier.account_id != run.account_id
                or earlier.topic_id != run.topic_id or row.run_id != earlier.id
                or earlier.state != (confirmed_state(earlier) if row.policy_version in (GIVEUP_POLICY, GIVEUP_SCORE_POLICY) else "SETTLED")):
            raise invalid()
        seen.add(earlier.id)
        previous.append(completion(earlier, row.facts))
    before = rules.evaluate(tuple(previous))
    after = rules.evaluate((*previous, completion(run, known)))
    extra = {}
    if policy in VARIANT_POLICIES:
        from terralocal.server.domain.rogue_ending_variants import facts as variant

        variants = data.rogue_ending_variants
        prior = tuple(variant(earlier, row.facts) for earlier, row in prefix)
        before = dict(before) | dict(variants.evaluate(prior))
        after = dict(after) | dict(variants.evaluate((*prior, variant(run, known))))
        if (type(attained) is not tuple or tuple(sorted(set(attained))) != attained
                or any(key not in variants.conditions for key in attained)):
            raise invalid()
        # R28 can already have been attained via an explicitly admitted owned
        # acquisition. It must never be announced/rewarded as a new unlock.
        extra = {"variant_rules": variants.fingerprint, "attained": list(attained)}
    elif policy != POLICY or attained:
        raise invalid()
    if policy in DEPLOYMENT_POLICIES:
        from terralocal.server.domain.rogue_deployment_goals import facts as deployment
        from terralocal.server.gamedata.rogue_deployment_goals import RunDeployment

        if (type(deployment_prefix) is not tuple or len(deployment_prefix) != len(prefix)
                or any(type(saved) is not RunDeployment or saved.id != earlier.id
                       or saved.completion != completion(earlier, row.facts)
                       for saved, (earlier, row) in zip(deployment_prefix, prefix, strict=True))):
            raise invalid()
        deployments = data.rogue_deployment_goals
        before = dict(before) | dict(deployments.evaluate(deployment_prefix))
        after = dict(after) | dict(deployments.evaluate((*deployment_prefix, deployment(run, known))))
        extra |= {"deployment_rules": deployments.fingerprint,
                  "deployment_history": fingerprint([[r.id, r.minimum, r.unknown] for r in deployment_prefix])}
    elif deployment_prefix is not None:
        raise invalid()
    capacity_keys = []
    if policy in CAPACITY_POLICIES:
        from terralocal.server.domain.rogue_capacity_notices import CapacityNotice
        from terralocal.server.gamedata.rogue_capacity_unlocks import ITEM

        if (type(capacity_scope) is not CapacityNotice or capacity_scope.run_id != run.id
                or any(type(v) is not bool for v in (capacity_scope.before, capacity_scope.after, capacity_scope.attained))
                or capacity_scope.before and not capacity_scope.after
                or type(capacity_scope.history_hash) is not str or len(capacity_scope.history_hash) != 64
                or any(c not in "0123456789abcdef" for c in capacity_scope.history_hash)):
            raise invalid()
        # Numeric progress increases below13 never count as a new unlock.
        if capacity_scope.after and not capacity_scope.before and not capacity_scope.attained:
            capacity_keys.append(ITEM)
        extra |= {"capacity_rules": data.rogue_capacity_unlocks.fingerprint,
                  "capacity_history": capacity_scope.history_hash}
    elif capacity_scope is not None:
        raise invalid()
    entries = data.rogue_relic_archive.entries
    keys = sorted([key for key in after if key not in attained and after[key].current > before[key].current] + capacity_keys,
                  key=lambda key: (entries[key].group, entries[key].sort, entries[key].order, key))
    return {"base_policy": base_policy, "sequence": len(prefix),
            "previous": {"run": prefix[-1][0].id, "hash": prefix[-1][1].rule_hash} if prefix else None,
            "rules": fingerprint({"policy": REWARD_POLICY, "source": SOURCE, "per_item": PER_ITEM,
                                  "goals": rules.fingerprint, "archive": data.rogue_relic_archive.fingerprint}),
            "unlocks": keys, **extra}


def grant(score_rules, known, after, *, max_items=20):
    """Apply the extra source after game score, with existing caps and carry."""
    note = known["notification"]
    keys = note["unlocks"]
    if type(keys) is not list or len(keys) > max_items or len(set(keys)) != len(keys):
        raise invalid()
    windows = [row for row in score_rules.updates if row["updateTime"] <= known["ended"]
               and (row["endTime"] == -1 or known["ended"] < row["endTime"])]
    if len(windows) != 1:
        raise invalid()
    bp, grow = after["bp"], after["grow"]
    gained = min(len(keys) * PER_ITEM, max(0, windows[0]["maxBpCount"] - bp))
    gp = min(score_rules.grow_cap - grow, (bp + gained) // 10 - bp // 10)
    return {"cnt": gained, "from": bp, "to": bp + gained}, gp
