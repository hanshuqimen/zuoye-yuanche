"""Version-bound modern topic profiles and preferences; no fabricated runs."""

import json
import sqlite3
from contextlib import closing
from types import SimpleNamespace

from pydantic import ValidationError
from sqlalchemy import func, select

from terralocal.server.domain.clock import ServerClock
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_reads import snapshot_scope
from terralocal.server.gamedata.repository import canonical
from terralocal.server.persistence import models as m
from terralocal.server.protocol.roguelike_state import OuterState

POLICY = "rogue-topic-profile-v1"
MAX_OUTER_BYTES = 2 * 1024 * 1024


def available(data) -> bool:
    return data is not None and "roguelike_topic_table" in data.manifest["tables"]


def invalid() -> DomainError:
    return DomainError("ROGUE_STATE_INCOMPATIBLE", "集成战略存档与当前数据或状态模型不匹配；请保留原存档", 503)


def outer_state(value) -> dict:
    """Do not silently replace missing persisted balances with zero defaults."""
    try:
        result = OuterState.model_validate(value).model_dump()
        if value != result or len(canonical(result)) > MAX_OUTER_BYTES:
            raise invalid()
        # These nested contracts have not yet been admitted. An unknown saved
        # mission/history/activity must fail rather than reach the client as an
        # arbitrary dictionary or be replaced with a successful empty result.
        if (result["mission"]["list"] or result["record"]["history"]
                or result["collect"]["nodeUpgrade"] or result["activity"]["roguelikeActivitySeedModeDatas"]):
            raise invalid()
        return result
    except (ValidationError, TypeError, ValueError) as exc:
        raise invalid() from exc


def preflight(data, path, *, require_existing_binding: bool = False) -> None:
    from terralocal.server.domain.rogue_banks import preflight as bank_preflight

    bank_states = bank_preflight(data, path) or {}
    from terralocal.server.domain.rogue_progress import preflight as floor_preflight

    floor_preflight(data, path)
    from terralocal.server.domain.rogue_shops import preflight as shop_preflight

    shop_preflight(path)
    from terralocal.server.domain.rogue_visits import preflight as visit_preflight

    visit_preflight(path)
    enabled = available(data)
    catalog = data.rogue_topics if enabled else None
    if enabled and "rogue_1" in catalog.topics:
        _ = data.rogue_initial
        _ = data.rogue_recruit
        from terralocal.server.gamedata.rogue_endings import available as endings_available

        if endings_available(data):
            _ = data.rogue_endings
    from terralocal.server.domain.rogue_loot_plans import preflight as loot_preflight

    loot_preflight(data, path)
    from terralocal.server.domain.rogue_ending import preflight as ending_preflight

    ending_preflight(data, path)
    from terralocal.server.domain.rogue_settlement import preflight as settlement_preflight

    settlement_preflight(path)
    from terralocal.server.domain.rogue_runs import preflight as run_preflight

    run_preflight(data, path)
    from terralocal.server.domain.rogue_giveup import preflight as giveup_preflight

    giveup_preflight(data, path)
    from terralocal.server.domain.rogue_map_drafts import preflight as draft_preflight

    draft_preflight(data, path)
    from terralocal.server.domain.rogue_battle import preflight as battle_preflight

    battle_preflight(data, path)
    if not path.exists():
        return
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        accounts = conn.execute("SELECT account_id,gamedata_hash,policy_version,pinned FROM rlv2_accounts").fetchall() \
            if "rlv2_accounts" in tables else []
        rows = conn.execute("SELECT account_id,topic_id,state FROM rlv2_topics").fetchall() \
            if "rlv2_topics" in tables else []
        from terralocal.server.domain.rogue_collection import CollectionFacts, verified_on_disk
        now = 0
        if any(topic == "rogue_1" for _, topic, _ in rows):
            clock = conn.execute("SELECT mode,fixed_at,offset FROM server_clock WHERE id=1").fetchone()
            if clock is None:
                raise ValueError(invalid().message)
            now = ServerClock(SimpleNamespace(mode=clock[0], fixed_at=clock[1], offset=clock[2])).now()

        try:
            discovered = verified_on_disk(data, conn, bank_states=bank_states)
            from terralocal.server.domain.rogue_band_records import verified_on_disk as band_records

            completions = band_records(data, conn)
        except (DomainError, ValueError, KeyError, TypeError, AttributeError) as exc:
            raise ValueError(invalid().message) from exc
        if require_existing_binding and "accounts" in tables:
            missing = (conn.execute("SELECT 1 FROM accounts a LEFT JOIN rlv2_accounts r "
                "ON a.id=r.account_id WHERE r.account_id IS NULL LIMIT 1").fetchone()
                if "rlv2_accounts" in tables else conn.execute("SELECT 1 FROM accounts LIMIT 1").fetchone())
            if missing:
                raise ValueError("独立集成战略测试配置需要新存档，不能自动转换已有账号的版本绑定")
    if not accounts and not rows:
        return
    if not enabled:
        raise ValueError(invalid().message)
    known = {}
    for account_id, digest, policy, pinned in accounts:
        if (digest != data.manifest["hash"] or policy != POLICY
                or (pinned is not None and pinned not in catalog.topics)):
            raise ValueError(invalid().message)
        known[account_id] = set()
    try:
        for account_id, topic_id, value in rows:
            if account_id not in known or topic_id not in catalog.topics:
                raise invalid()
            state = outer_state(json.loads(value))
            if topic_id == "rogue_1":
                from terralocal.server.domain.rogue_collection import project

                facts = discovered.get(account_id, CollectionFacts())
                project(state, facts.attained, facts.eligibility)
                from terralocal.server.domain.rogue_tool_archive import project as project_tools

                project_tools(data, state, facts.tools, now)
                from terralocal.server.domain.rogue_capsules import project as project_capsules

                project_capsules(data, state, facts.capsules, now)
                from terralocal.server.domain.rogue_band_records import project as project_bands

                project_bands(state, completions.get(account_id, {}))
            known[account_id].add(topic_id)
        if any(topics != set(catalog.topics) for topics in known.values()):
            raise invalid()
    except (DomainError, ValueError) as exc:
        raise ValueError(invalid().message) from exc


def _account(ctx):
    if not available(ctx.data):
        raise DomainError("ROGUE_DATA_MISSING", "缺少匹配的现代集成战略主题表", 503)
    account = ctx.session.get(m.RogueTopicAccount, ctx.account_id)
    if (account is None or account.gamedata_hash != ctx.data.manifest["hash"] or account.policy_version != POLICY
            or (account.pinned is not None and account.pinned not in ctx.data.rogue_topics.topics)):
        raise invalid()
    return account


def initialize(ctx) -> bool:
    if not available(ctx.data):
        return False
    if ctx.session.get(m.RogueTopicAccount, ctx.account_id) is not None:
        _account(ctx)
        return False
    ctx.session.add(m.RogueTopicAccount(account_id=ctx.account_id, gamedata_hash=ctx.data.manifest["hash"],
        policy_version=POLICY, pinned=None, initialized_at=ctx.now))
    ctx.session.flush()
    for topic_id in ctx.data.rogue_topics.topics:
        ctx.session.add(m.RogueTopicOuter(account_id=ctx.account_id, topic_id=topic_id,
                                        state=OuterState().model_dump()))
    ctx.session.flush()
    return True


@snapshot_scope
def snapshot(ctx) -> dict:
    from terralocal.server.domain.rogue_band_records import facts as band_records
    from terralocal.server.domain.rogue_collection import facts
    from terralocal.server.domain.rogue_runs import snapshot as run_snapshot

    account = _account(ctx)
    from terralocal.server.domain.rogue_banks import verify_account

    verify_account(ctx)
    rows = ctx.read_rows(m.RogueTopicOuter)
    if {row.topic_id for row in rows} != set(ctx.data.rogue_topics.topics):
        raise invalid()
    starts = dict(ctx.session.execute(select(m.RogueTopicRun.topic_id, func.max(m.RogueTopicRun.created_at))
        .where(m.RogueTopicRun.account_id == ctx.account_id).group_by(m.RogueTopicRun.topic_id)).all())
    collection = facts(ctx)
    completions = band_records(ctx)
    return {"current": run_snapshot(ctx), "outer": {row.topic_id: visible_outer(
        ctx.data, row.topic_id, row.state, last_start=starts.get(row.topic_id),
        attained=collection.attained, eligibility=collection.eligibility, completions=completions,
        tools=collection.tools, capsules=collection.capsules, at=ctx.now)
                                                    for row in rows},
            "pinned": account.pinned}


def visible_outer(data, topic_id, value, *, at, last_start=None, attained=(), eligibility=(), completions=None,
                  tools=(), capsules=()) -> dict:
    """Project intrinsic base availability, without inventing earned progress.

    This local bootstrap rule is limited to first-theme EASY/0 and NORMAL/0,
    its sole no-condition band and three no-condition recruit combinations.
    State1 means available/unattained; state2 achievements are never inferred.
    Other grades/conditions are not inferred by this bootstrap. Explicit
    roster-goal facts are supplied separately by the validated run adapter.
    """
    state = outer_state(value)
    # 0019 initial builds wrote the end time here. Project the authoritative
    # saved start without rewriting historical saves during a read/sync.
    if last_start is not None:
        state["record"]["last"] = last_start
    if topic_id != "rogue_1":
        return state
    from terralocal.server.domain.rogue_collection import project

    project(state, attained, eligibility)
    from terralocal.server.domain.rogue_tool_archive import project as project_tools

    project_tools(data, state, tools, at)
    from terralocal.server.domain.rogue_capsules import project as project_capsules

    project_capsules(data, state, capsules, at)
    from terralocal.server.domain.rogue_band_records import project as project_bands

    project_bands(state, completions or {})
    rules = data.rogue_initial
    collect = state["collect"]
    for section, keys in (("mode", rules.configs), ("band", (rules.band,)), ("recruitSet", rules.groups)):
        for key in keys:
            record = collect[section].setdefault(key, {"state": 1, "progress": []})
            record["state"] = max(record["state"], 1)
    for mode in rules.configs:
        grade = collect["modeGrade"].setdefault(mode, {}).setdefault("0", {"state": 1})
        grade["state"] = max(grade["state"], 1)
    return state


def pin(ctx, topic_id: str | None) -> dict:
    account = _account(ctx)
    # Null and empty strings both clear a reference-type preference. No game
    # unlock, run, collection progress or reward is granted by pinning a theme.
    if topic_id:
        ctx.data.rogue_topics.topic(topic_id, at=ctx.now)
    account.pinned = topic_id or None
    return {}
