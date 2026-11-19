"""Discovery and explicit roster goals from retained, validated run facts.

No read rewrites an old save. Discovery survives abandonment because the owned
run and purchase journal are retained. Five matched roster goals have their
own mode gate; other quests and natural supply remain separate contracts.
"""

import json
import sqlite3
from dataclasses import dataclass
from types import SimpleNamespace

from sqlalchemy import select

from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.rogue_bank_items import available as bank_items_available
from terralocal.server.gamedata.rogue_base_relics import available as base_relics_available
from terralocal.server.gamedata.rogue_battle_effects import SOURCES, supported
from terralocal.server.gamedata.rogue_capacity_relics import SOURCES as CAPACITY_SOURCES
from terralocal.server.gamedata.rogue_capacity_relics import supported as capacity_supported
from terralocal.server.gamedata.rogue_capacity_unlocks import RunCapacity
from terralocal.server.gamedata.rogue_capacity_unlocks import available as capacities_available
from terralocal.server.gamedata.rogue_currency_relics import SOURCES as CURRENCY_SOURCES
from terralocal.server.gamedata.rogue_currency_relics import supported as currency_supported
from terralocal.server.gamedata.rogue_deployment_goals import available as deployments_available
from terralocal.server.gamedata.rogue_ending_unlocks import RunCompletion
from terralocal.server.gamedata.rogue_ending_unlocks import available as endings_available
from terralocal.server.gamedata.rogue_ending_variants import available as variants_available
from terralocal.server.gamedata.rogue_floor_unlocks import RunFloors
from terralocal.server.gamedata.rogue_floor_unlocks import available as floors_available
from terralocal.server.gamedata.rogue_gold_relics import SOURCES as GOLD_SOURCES
from terralocal.server.gamedata.rogue_gold_relics import supported as gold_supported
from terralocal.server.gamedata.rogue_life_relics import SOURCES as LIFE_SOURCES
from terralocal.server.gamedata.rogue_life_relics import supported as life_supported
from terralocal.server.gamedata.rogue_recruit_costs import FILTERS
from terralocal.server.gamedata.rogue_resource_relics import SOURCES as RESOURCE_SOURCES
from terralocal.server.gamedata.rogue_resource_relics import supported as resource_supported
from terralocal.server.gamedata.rogue_roster_unlocks import RunRoster, available
from terralocal.server.persistence import models as m


def invalid():
    return DomainError("ROGUE_COLLECTION_INCOMPATIBLE", "收藏品图鉴与已核对的获得记录不一致；请保留原存档", 503)


@dataclass(frozen=True)
class CollectionFacts:
    attained: frozenset[str] = frozenset()
    eligibility: tuple = ()
    tools: frozenset[str] = frozenset()
    capsules: frozenset[str] = frozenset()


def roster(data, mode, grade, started_at, characters):
    return RunRoster(mode, grade, started_at, tuple(
        (char["charId"], data.character(char["charId"])["rarity"]) for char in characters))


def progress(rules, rosters):
    return tuple(sorted(rules.evaluate(tuple(rosters)).items())) if rules is not None else ()


def floors(run, layout):
    from terralocal.server.domain.rogue_progress import Layout

    completed = tuple(layout.zones[t.zone - 1].id for t in layout.journal) if isinstance(layout, Layout) else ()
    return RunFloors(run.mode, run.grade, run.created_at, completed)


def completion(run, facts):
    return RunCompletion(run.mode, run.grade, run.created_at, facts["ended"],
                         facts.get("success", 0), facts.get("ending"))


def capacity(data, run, replayed):
    from terralocal.server.domain.rogue_settlement import initial

    peak = initial(data, run)["squad_capacity"] if replayed is None else replayed.capacity_peak
    return RunCapacity(run.mode, run.grade, run.created_at, peak)


def capacities_on_disk(data, connection, *, tool_facts=None, capsule_facts=None, include_capacity=True):
    """Called only after full run preflight; recompute peaks, never trust sums."""
    from terralocal.server.domain.rogue_settlement import state_on_disk

    result = {account: [] for account, in connection.execute(
        "SELECT account_id FROM rlv2_topics WHERE topic_id='rogue_1'")}
    previous = connection.row_factory
    try:
        connection.row_factory = sqlite3.Row
        for raw in connection.execute("SELECT * FROM rlv2_runs WHERE topic_id='rogue_1'"):
            run = SimpleNamespace(**dict(raw))
            tickets = []
            for raw_ticket in connection.execute("SELECT * FROM rlv2_tickets WHERE run_id=? ORDER BY ordinal", (run.id,)):
                value = dict(raw_ticket)
                for field in ("elite_pool", "direct_pool"):
                    if field in value:
                        value[field] = json.loads(value[field])
                tickets.append(SimpleNamespace(**value))
            replayed = state_on_disk(data, connection, run, tickets)
            if include_capacity:
                result.setdefault(run.account_id, []).append(capacity(data, run, replayed))
            if tool_facts is not None:
                from terralocal.server.domain.rogue_tool_archive import attained

                tool_facts.setdefault(run.account_id, set()).update(attained(replayed))
            if capsule_facts is not None:
                from terralocal.server.domain.rogue_capsules import attained as capsules

                capsule_facts.setdefault(run.account_id, set()).update(capsules(replayed))
    finally:
        connection.row_factory = previous
    return result


def admit(data, keys):
    entries = data.rogue_relic_archive.entries
    for key in keys:
        entry = entries[key]
        if ((key not in FILTERS and not supported(data, key) and not capacity_supported(data, key)
             and not gold_supported(data, key) and not resource_supported(data, key) and not currency_supported(data, key)
             and not life_supported(data, key)) or entry.special
                or key in FILTERS and entry.enrollment is not None):
            raise invalid()


def verified_on_disk(data, connection, *, bank_states):
    """Call after rogue_runs.preflight has validated every retained journal."""
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {"rlv2_runs", "rlv2_relics"} <= tables:
        return {}
    found = {}
    for account, topic, item in connection.execute("SELECT r.account_id,r.topic_id,l.item_id "
            "FROM rlv2_runs r JOIN rlv2_relics l ON l.run_id=r.id WHERE l.ordinal>0"):
        if topic != "rogue_1":
            raise invalid()
        found.setdefault(account, set()).add(item)
    if found:
        admit(data, {key for keys in found.values() for key in keys})
    rules = data.rogue_roster_unlocks if available(data) else None
    capacity_rules = data.rogue_capacity_unlocks if capacities_available(data) else None
    from terralocal.server.domain.rogue_tool_archive import available as tools_available

    tool_facts = {} if tools_available(data) else None
    from terralocal.server.gamedata.rogue_capsules import available as capsules_available

    capsule_facts = {} if capsules_available(data) else None
    capacity_runs = capacities_on_disk(data, connection, tool_facts=tool_facts, capsule_facts=capsule_facts,
        include_capacity=capacity_rules is not None) if capacity_rules is not None or tool_facts is not None or capsule_facts is not None else {}
    rosters, by_run = {}, {}
    if rules is not None:
        for ident, account, mode, grade, at in connection.execute(
                "SELECT id,account_id,mode,grade,created_at FROM rlv2_runs WHERE topic_id='rogue_1'"):
            by_run[ident] = (account, mode, grade, at, [])
        if {"rlv2_chars", "rlv2_recruit_options"} <= tables:
            for ident, value in connection.execute("SELECT c.run_id,o.character FROM rlv2_chars c "
                    "JOIN rlv2_recruit_options o ON o.run_id=c.run_id AND o.ticket_ordinal=c.ticket_ordinal "
                    "AND o.ordinal=c.option_ordinal ORDER BY c.run_id,c.ordinal"):
                if ident in by_run:
                    by_run[ident][4].append(json.loads(value))
        for account, mode, grade, at, characters in by_run.values():
            rosters.setdefault(account, []).append(roster(data, mode, grade, at, characters))
        # A no-run account must not bootstrap a claimed completed goal either.
        for account, in connection.execute("SELECT account_id FROM rlv2_topics WHERE topic_id='rogue_1'"):
            rosters.setdefault(account, [])
    floor_rules = data.rogue_floor_unlocks if floors_available(data) else None
    floor_runs = {}
    if floor_rules is not None:
        from terralocal.server.domain.rogue_progress import on_disk

        previous = connection.row_factory
        try:
            connection.row_factory = sqlite3.Row
            for raw in connection.execute("SELECT * FROM rlv2_runs WHERE topic_id='rogue_1'"):
                run = SimpleNamespace(**dict(raw))
                layout = on_disk(data, connection, run) if "rlv2_map_drafts" in tables else None
                floor_runs.setdefault(run.account_id, []).append(floors(run, layout))
        finally:
            connection.row_factory = previous
    ending_rules = data.rogue_ending_unlocks if endings_available(data) else None
    variant_rules = data.rogue_ending_variants if variants_available(data) else None
    deployment_rules = data.rogue_deployment_goals if deployments_available(data) else None
    endings, variants, deployments = {}, {}, {}
    if ending_rules is not None and "rlv2_game_settlements" in tables:
        for ident, data_hash, account, mode, grade, at, band, hope_max, hope_cost, gold, value in connection.execute(
                "SELECT r.id,r.gamedata_hash,r.account_id,r.mode,r.grade,r.created_at,r.band_id,r.hope_max,r.hope_cost,r.gold,s.facts FROM rlv2_runs r "
                "JOIN rlv2_game_settlements s ON s.run_id=r.id WHERE r.topic_id='rogue_1' AND r.state='SETTLED'"):
            run = SimpleNamespace(id=ident, gamedata_hash=data_hash, account_id=account, topic_id="rogue_1",
                                  mode=mode, grade=grade, created_at=at, band_id=band,
                                  hope_max=hope_max, hope_cost=hope_cost, gold=gold)
            known = json.loads(value)
            endings.setdefault(account, []).append(completion(run, known))
            if variant_rules is not None:
                from terralocal.server.domain.rogue_ending_variants import facts as variant

                variants.setdefault(account, []).append(variant(run, known))
            if deployment_rules is not None:
                from terralocal.server.domain import rogue_deployment_goals as deployment
                from terralocal.server.domain.rogue_settlement import read_rows

                previous = connection.row_factory
                try:
                    connection.row_factory = sqlite3.Row
                    scope = deployment.on_disk(data, connection, run, read_rows(connection, run.id))
                finally:
                    connection.row_factory = previous
                deployments.setdefault(account, []).append(deployment.facts(run, known | {"combat": scope}))
    # Supplied only by the preceding read-only bank preflight. All score/run
    # histories have also been independently checked before this projection.
    bank_progress = {}
    if bank_items_available(data):
        bank_rules = data.rogue_bank_items
        for account, in connection.execute("SELECT account_id FROM rlv2_topics WHERE topic_id='rogue_1'"):
            verified = bank_states.get(account)
            bank_progress[account] = tuple(sorted(bank_rules.evaluate_verified(None if verified is None else verified[0]).items()))
    base_progress = {}
    if base_relics_available(data):
        from terralocal.server.domain.clock import ServerClock

        if "server_clock" not in tables:
            raise invalid()
        raw = connection.execute("SELECT mode,fixed_at,offset FROM server_clock WHERE id=1").fetchone()
        if raw is None:
            raise invalid()
        at = ServerClock(SimpleNamespace(mode=raw[0], fixed_at=raw[1], offset=raw[2])).now()
        intrinsic = tuple(sorted(data.rogue_base_relics.evaluate(at).items()))
        for account, in connection.execute("SELECT account_id FROM rlv2_topics WHERE topic_id='rogue_1'"):
            base_progress[account] = intrinsic
    return {account: CollectionFacts(frozenset(found.get(account, ())),
                progress(rules, rosters.get(account, ())) + progress(floor_rules, floor_runs.get(account, ()))
                + progress(ending_rules, endings.get(account, ()))
                + progress(variant_rules, variants.get(account, ()))
                + progress(deployment_rules, deployments.get(account, ()))
                + progress(capacity_rules, capacity_runs.get(account, ())) + bank_progress.get(account, ())
                + base_progress.get(account, ()), frozenset((tool_facts or {}).get(account, ())),
                frozenset((capsule_facts or {}).get(account, ())))
            for account in found.keys() | rosters.keys() | endings.keys() | capacity_runs.keys()
                           | bank_progress.keys() | base_progress.keys() | (tool_facts or {}).keys() | (capsule_facts or {}).keys()}


def facts(ctx) -> CollectionFacts:
    from terralocal.server.domain.rogue_runs import validated

    ctx.session.flush()
    try:
        rules = ctx.data.rogue_roster_unlocks if available(ctx.data) else None
        capacity_rules = ctx.data.rogue_capacity_unlocks if capacities_available(ctx.data) else None
        floor_rules = ctx.data.rogue_floor_unlocks if floors_available(ctx.data) else None
        ending_rules = ctx.data.rogue_ending_unlocks if endings_available(ctx.data) else None
        variant_rules = ctx.data.rogue_ending_variants if variants_available(ctx.data) else None
        deployment_rules = ctx.data.rogue_deployment_goals if deployments_available(ctx.data) else None
        query = select(m.RogueTopicRun).where(m.RogueTopicRun.account_id == ctx.account_id,
                                            m.RogueTopicRun.topic_id == "rogue_1")
        from terralocal.server.domain.rogue_capsules import attained as capsules
        from terralocal.server.domain.rogue_tool_archive import attained
        from terralocal.server.domain.rogue_tool_archive import available as tools_available
        from terralocal.server.gamedata.rogue_capsules import available as capsules_available

        if rules is None and ending_rules is None and capacity_rules is None and not tools_available(ctx.data) and not capsules_available(ctx.data):
            query = query.join(m.RogueRunRelic).where(m.RogueRunRelic.ordinal > 0).distinct()
        runs = ctx.session.scalars(query).all()
        deployments = []
        if ending_rules is not None:
            from terralocal.server.domain.rogue_ending import history_in_session

            settled = {r.id: row for r, row in history_in_session(ctx, deployment_history_out=deployments)}
        found, rosters, floor_runs, endings, variants = set(), [], [], [], []
        tools, capsule_items = set(), set()
        capacity_runs = []
        for run in runs:
            replayed = []
            children = validated(ctx, run, progress_out=replayed)
            tools.update(attained(replayed[0]))
            capsule_items.update(capsules(replayed[0]))
            if capacity_rules is not None:
                capacity_runs.append(capacity(ctx.data, run, replayed[0]))
            for relic in children[1]:
                if relic.ordinal == 0:  # Starting band is not an archive relic.
                    continue
                found.add(relic.item_id)
            if rules is not None:
                options = {(o.ticket_ordinal, o.ordinal): o for o in children[3]}
                characters = [options[c.ticket_ordinal, c.option_ordinal].character for c in children[4]]
                rosters.append(roster(ctx.data, run.mode, run.grade, run.created_at, characters))
            if floor_rules is not None:
                from terralocal.server.domain.rogue_progress import in_session

                floor_runs.append(floors(run, in_session(ctx, run)))
            if ending_rules is not None and run.state == "SETTLED":
                from terralocal.server.domain.rogue_band_records import validated_settlement

                row = validated_settlement(ctx, run, children, history=settled)
                endings.append(completion(run, row.facts))
                if variant_rules is not None:
                    from terralocal.server.domain.rogue_ending_variants import facts as variant

                    variants.append(variant(run, row.facts))
        if found:
            admit(ctx.data, found)
        bank_progress = ()
        if bank_items_available(ctx.data):
            from terralocal.server.domain.rogue_banks import verify_account

            verified = verify_account(ctx)
            if verified is not None and ending_rules is None:
                from terralocal.server.domain.rogue_ending import history_in_session

                history_in_session(ctx)
            bank_progress = tuple(sorted(ctx.data.rogue_bank_items.evaluate_verified(
                None if verified is None else verified[0]).items()))
        base_progress = tuple(sorted(ctx.data.rogue_base_relics.evaluate(ctx.now).items())) \
            if base_relics_available(ctx.data) else ()
        return CollectionFacts(frozenset(found), progress(rules, rosters) + progress(floor_rules, floor_runs)
                               + progress(ending_rules, endings) + progress(variant_rules, variants)
                               + progress(deployment_rules, deployments) + progress(capacity_rules, capacity_runs)
                               + bank_progress + base_progress, frozenset(tools), frozenset(capsule_items))
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise invalid() from exc


def project(state, found, eligibility=()):
    relics = state["collect"]["relic"]
    # Do not accept a claimed attained state in this admitted family without
    # the actual purchase/inventory/source history, even on a no-run account.
    if any(key in FILTERS.keys() | SOURCES.keys() | CAPACITY_SOURCES.keys() | GOLD_SOURCES.keys() | RESOURCE_SOURCES.keys() | CURRENCY_SOURCES.keys() | LIFE_SOURCES.keys()
           and row["state"] == 2 and key not in found
           for key, row in relics.items()):
        raise invalid()
    for key, value in eligibility:
        saved = relics.get(key)
        expected = value.wire()
        if saved is not None:
            claimed = saved["progress"]
            if (saved["state"] == 2 and key not in found
                    or saved["state"] == 1 and not expected["state"]
                    or claimed and (not expected["progress"] or len(claimed) != 2
                                    or claimed[1] != value.target or claimed[0] > value.current)):
                raise invalid()
        relics[key] = expected
    for key in sorted(found):
        relics[key] = {"state": 2, "progress": []}
    return state
