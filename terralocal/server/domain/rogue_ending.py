"""Atomic acknowledgement of admitted IS2 natural-defeat endings.

Scoring is a versioned community-rule adapter, not official server code.
Unknown modes/effects never settle for an empty successful response.
"""

import json
import sqlite3
from contextlib import closing
from copy import deepcopy
from dataclasses import asdict
from types import SimpleNamespace

from sqlalchemy import select

from terralocal.server.domain import rogue_completion_rewards as completion_rewards
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_giveup import SCORE_POLICY as GIVEUP_SCORE_POLICY
from terralocal.server.domain.rogue_giveup import confirmed_state as giveup_confirmed_state
from terralocal.server.domain.rogue_progress import Layout, zone_for
from terralocal.server.domain.rogue_terminal import ENDING_POLICY as BOSS_POLICY
from terralocal.server.domain.rogue_terminal import POLICY as TERMINAL_POLICY
from terralocal.server.gamedata.repository import canonical, fingerprint
from terralocal.server.gamedata.rogue_capacity_unlocks import available as capacities_available
from terralocal.server.gamedata.rogue_deployment_goals import available as deployments_available
from terralocal.server.gamedata.rogue_ending_unlocks import available as completion_available
from terralocal.server.gamedata.rogue_ending_variants import available as variants_available
from terralocal.server.gamedata.rogue_score import FLOORS, POLICY, FirstThemeScore
from terralocal.server.persistence import models as m

SCENE_POLICY = "rogue1-normal0-prts-score-scenes-v2"
SHOP_POLICY = "rogue1-normal0-prts-score-shops-v3"
FLOOR_POLICY = "rogue1-normal0-prts-score-floors-v4"
RELIC_POLICY = "rogue1-normal0-prts-score-cost-relics-v5"
GIVEUP_POLICIES = frozenset({GIVEUP_SCORE_POLICY, completion_rewards.GIVEUP_POLICY})
LEGACY_POLICIES = frozenset({POLICY, SCENE_POLICY, SHOP_POLICY, FLOOR_POLICY, RELIC_POLICY, BOSS_POLICY, GIVEUP_SCORE_POLICY})
POLICIES = LEGACY_POLICIES | completion_rewards.ORDERED_POLICIES


def invalid():
    return DomainError("ROGUE_ENDING_INCOMPATIBLE", "探索结束记录不一致；请保留原存档", 503)


def balances(state):
    return {"bp": state["bp"]["point"], "grow": state["buff"]["pointOwned"],
            "stages": deepcopy(state["record"]["stageCnt"])}


def collected_relics(shops, scenes=(), records=()):
    from terralocal.server.domain.rogue_relics import MAX_RELICS
    from terralocal.server.domain.rogue_settlement import relic_grants as battle_grants
    from terralocal.server.domain.rogue_visits import relic_grants

    count = 0
    for shop in shops:
        if shop.state == "PREPARED":
            continue
        for purchase in shop.purchases:
            if type(purchase) is not dict or set(purchase) != {"index", "at", "ticket"}:
                raise invalid()
            count += purchase["ticket"] is None
    count += sum(len(relic_grants(scene)) for scene in scenes if scene.state != "PREPARED")
    count += sum(len(battle_grants(row)) for row in records)
    if count > MAX_RELICS:
        raise invalid()
    return count


def visited_scenes(ctx, run):
    from terralocal.server.domain import rogue_visits

    draft = ctx.session.get(m.RogueMapDraft, run.id)
    return rogue_visits.bind_visited_content(ctx.data, run, draft, rogue_visits.rows(ctx.session, run.id))


def facts(run, records, chars, battles, scenes=(), shops=(), *, policy=POLICY, layout=None, data=None):
    if policy == BOSS_POLICY:
        from terralocal.server.domain.rogue_terminal import ending_facts

        return ending_facts(data, run, records, chars, battles, scenes, shops, layout)
    completed = len(layout.journal) if isinstance(layout, Layout) else 0
    if (completed and policy not in (FLOOR_POLICY, RELIC_POLICY) or policy == FLOOR_POLICY and not completed):
        raise invalid()
    from terralocal.server.domain.rogue_settlement import LOOT_POLICY

    collected = collected_relics(shops, scenes, records)
    if bool(collected) != (policy == RELIC_POLICY):
        raise invalid()
    if completed >= len(FLOORS):
        raise DomainError("ROGUE_ENDING_UNSUPPORTED", "此楼层数量的评分规则尚未接通", 501)
    by_id = {b.id: b for b in battles}
    if (run.topic_id != "rogue_1" or run.mode != "NORMAL" or run.grade != 0 or run.hp != 0
            or not records or records[-1].effects.get("outcome") != "DEFEAT"
            or records[-1].completed_at is not None
            or any((r.effects["kind"] not in ("BATTLE_NORMAL", "BATTLE_ELITE", "BATTLE_BOSS")
                    or r.effects["kind"] != "BATTLE_NORMAL" and r.policy_version != LOOT_POLICY)
                or r.battle_id not in by_id or (
                r.effects["zone"] != zone_for(layout, by_id[r.battle_id]).id
                if completed else r.effects["zone"] != "zone_1") for r in records)
            or any(r.effects.get("outcome") == "DEFEAT" or r.completed_at is None for r in records[:-1])):
        raise DomainError("ROGUE_ENDING_UNSUPPORTED", "此探索结果的结束规则尚未接通", 501)
    # Completed floors come only from the validated owned transition journal.
    # Upgraded actors, non-band relics and boss results remain unsupported.
    clears = [r for r in records if r.effects.get("outcome") != "DEFEAT"]
    stages = {}
    if set(by_id) != {r.battle_id for r in records}:
        raise invalid()
    for row in clears:
        stage = by_id[row.battle_id].stage_id
        stages[stage] = stages.get(stage, 0) + 1
    entered = [s for s in scenes if s.state != "PREPARED"]
    traded = [s for s in shops if s.state != "PREPARED"]
    if (policy not in POLICIES or any(s.state != "FINISHED" for s in entered)
            or policy == POLICY and entered or policy not in (SHOP_POLICY, FLOOR_POLICY, RELIC_POLICY) and traded
            or policy == SHOP_POLICY and not traded
            or any(s.state != "FINISHED" or type(s.ended_at) is not int
                   or not run.created_at <= s.ended_at <= records[-1].created_at for s in traded)):
        raise invalid()
    # Gold/tickets do not count as relics. Current non-ticket shop receipts are
    # compiled unique effects, validated by run replay and immutable quotes.
    result = {"counts": [completed, len(records) + len(entered) + len(traded),
            *(sum(r.effects["kind"] == kind for r in clears) for kind in ("BATTLE_NORMAL", "BATTLE_ELITE", "BATTLE_BOSS")),
            collected, len(chars)],
            "stages": stages, "ended": records[-1].created_at,
            "battles": [[r.battle_id, r.rule_hash, fingerprint(r.facts)] for r in records]}
    if policy in (SCENE_POLICY, SHOP_POLICY, FLOOR_POLICY, RELIC_POLICY):
        result["scenes"] = [[s.id, s.rule_hash, fingerprint({"before": s.before, "steps": s.steps,
            "recruits": s.recruit_count, "entered": s.entered_at, "ended": s.ended_at})] for s in entered]
    if policy in (SHOP_POLICY, FLOOR_POLICY, RELIC_POLICY):
        result["shops"] = [[s.id, s.rule_hash, fingerprint({"before": s.before,
            "first_ticket": s.first_ticket, "purchases": s.purchases, "entered": s.entered_at,
            "ended": s.ended_at})] for s in traded]
    if policy == FLOOR_POLICY or policy == RELIC_POLICY and completed:
        result["floors"] = {"index": layout.index, "journal": [asdict(t) for t in layout.journal],
                            "maps": [fingerprint(z.wire()) for z in layout.zones]}
    return result


def calculate(data, run, known, before, *, policy=POLICY):
    if policy not in POLICIES:
        raise invalid()
    rules = FirstThemeScore(data)
    if (set(before) != {"bp", "grow", "stages"} or type(before["stages"]) is not dict
            or any(type(n) is not int or not 0 <= n < 2**31 for n in before["stages"].values())):
        raise invalid()
    detail, score, gain, grow = rules.calculate(known["counts"], before, known["ended"])
    stages = before["stages"].copy()
    for stage, n in known["stages"].items():
        stages[stage] = stages.get(stage, 0) + n
        if stages[stage] >= 2**31:
            raise invalid()
    after = {"bp": before["bp"] + gain, "grow": before["grow"] + grow, "stages": stages}
    zero = {"cnt": 0, "from": after["bp"], "to": after["bp"]}
    counts = known["counts"]
    response = {"game": {
        "brief": {"success": known.get("success", 0), "ending": known.get("ending"), "theme": run.topic_id, "mode": run.mode,
                  "band": run.band_id, "level": run.level},
        "record": {"cntZone": counts[0], "cntArrivedNode": counts[1], "cntBattle": counts[2],
                   "cntBattleElite": counts[3], "cntBattleBoss": counts[4],
                   "cntRecruitChar": counts[6], "cntUpgradeChar": 0},
        "score": {"detail": detail, "scoreFactor": 1, "score": score, "buff": 0,
                  "bp": {"cnt": gain, "from": before["bp"], "to": after["bp"]},
                  "gp": grow, "accumulation": []}, "monthTeam": None, "challenge": None},
        "outer": {"mission": {"before": [], "after": []}, "missionBp": zero.copy(),
                  "relicBp": zero.copy(), "totemBp": zero.copy(), "fragmentBp": zero.copy(),
                  "copperBp": zero.copy(), "relicUnlock": [], "totemUnlock": [], "fragmentUnlock": [],
                  "copperUnlock": [], "scrapUnlock": [], "gp": 0, "spOperatorInfo": [], "items": []}}
    rule = {"rules": rules.hash, "facts": known, "before": before}
    if policy in completion_rewards.ORDERED_POLICIES:
        bonus, extra_grow = completion_rewards.grant(rules, known, after,
            max_items=37 if policy in completion_rewards.CAPACITY_POLICIES
            else 36 if policy == completion_rewards.DEPLOYMENT_POLICY
            else 34 if policy == completion_rewards.VARIANT_POLICY else 20)
        response["outer"]["relicUnlock"] = known["notification"]["unlocks"].copy()
        response["outer"]["relicBp"] = bonus
        response["outer"]["gp"] = extra_grow
        after["bp"], after["grow"] = bonus["to"], after["grow"] + extra_grow
        for key in ("totemBp", "fragmentBp", "copperBp"):
            response["outer"][key] = {"cnt": 0, "from": after["bp"], "to": after["bp"]}
    if policy != POLICY:
        rule["ending_policy"] = policy
    return after, response, fingerprint(rule)


def base_policy(records, shops, scenes, layout):
    return (BOSS_POLICY if records and records[-1].policy_version == TERMINAL_POLICY
            else RELIC_POLICY if collected_relics(shops, scenes, records)
            else FLOOR_POLICY if isinstance(layout, Layout) and layout.journal
            else SHOP_POLICY if any(s.state != "PREPARED" for s in shops)
            else SCENE_POLICY if any(s.state != "PREPARED" for s in scenes) else POLICY)


def validate(data, run, records, chars, battles, row, scenes=(), shops=(), *, layout=None, prefix=None, attained=None,
             combat_scope=None, deployment_prefix=None, capacity_scope=None, closure_scope=None):
    try:
        selected = row.policy_version
        if selected in completion_rewards.ORDERED_POLICIES:
            if prefix is None or not completion_available(data):
                raise invalid()
            selected = (GIVEUP_SCORE_POLICY if row.policy_version == completion_rewards.GIVEUP_POLICY
                        else base_policy(records, shops, scenes, layout))
        if row.policy_version in GIVEUP_POLICIES:
            if closure_scope is None:
                raise invalid()
            known = deepcopy(closure_scope)
        else:
            if closure_scope is not None:
                raise invalid()
            known = facts(run, records, chars, battles, scenes, shops, policy=selected, layout=layout, data=data)
        if row.policy_version in completion_rewards.ORDERED_POLICIES:
            if row.policy_version in completion_rewards.VARIANT_POLICIES and (attained is None or not variants_available(data)):
                raise invalid()
            if row.policy_version in completion_rewards.DEPLOYMENT_POLICIES:
                if combat_scope is None or not deployments_available(data):
                    raise invalid()
                known["combat"] = combat_scope
            if row.policy_version in completion_rewards.CAPACITY_POLICIES:
                if capacity_scope is None or not capacities_available(data):
                    raise invalid()
            known["notification"] = completion_rewards.notification(data, run, known, selected, prefix,
                policy=row.policy_version, attained=attained or (), deployment_prefix=deployment_prefix,
                capacity_scope=capacity_scope)
        after, response, rule = calculate(data, run, known, row.before, policy=row.policy_version)
        if (row.run_id != run.id or row.policy_version not in POLICIES or row.rule_hash != rule
                or canonical(row.facts) != canonical(known) or canonical(row.after) != canonical(after)
                or canonical(row.response) != canonical(response)
                or run.state != (giveup_confirmed_state(run)
                                 if row.policy_version in GIVEUP_POLICIES else "SETTLED")
                or type(row.created_at) is not int or row.created_at < known["ended"]
                or run.ended_at != (known["ended"] if row.policy_version in GIVEUP_POLICIES else row.created_at)):
            raise invalid()
    except (DomainError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise invalid() from exc


def history_in_session(ctx, *, deployment_history_out=None):
    """Validate this owner's complete ledger once in its actual commit order."""
    from terralocal.server.domain import rogue_runs, rogue_settlement, rogue_shops
    from terralocal.server.domain.rogue_progress import in_session

    ctx.session.flush()
    from terralocal.server.domain.rogue_reads import facts

    known = facts(ctx)
    if known is not None and known.history is not None:
        history, deployments = known.history
        if deployment_history_out is not None:
            deployment_history_out.extend(deployments)
        return history
    try:
        entries = ctx.session.execute(select(m.RogueTopicRun, m.RogueGameSettlement)
            .join(m.RogueGameSettlement).where(m.RogueTopicRun.account_id == ctx.account_id,
                                             m.RogueTopicRun.topic_id == "rogue_1")).all()
        groups = completion_rewards.ordered_groups(entries, LEGACY_POLICIES)
        history = groups.get((ctx.account_id, "rogue_1"), ())
        prefix, deployments = [], []
        deployment_rules = deployments_available(ctx.data)
        for run, row in history:
            children = rogue_runs.validated(ctx, run)
            battles = ctx.session.scalars(select(m.RogueBattle).where(m.RogueBattle.run_id == run.id)).all()
            from terralocal.server.domain.rogue_ending_variants import attained_through_run

            attained = attained_through_run(ctx, run) if row.policy_version in completion_rewards.VARIANT_POLICIES else None
            records = rogue_settlement.rows(ctx.session, run.id)
            from terralocal.server.domain import rogue_deployment_goals as deployment

            scope = deployment.in_session(ctx, run, records) if deployment_rules else None
            capacity_scope = None
            if row.policy_version in completion_rewards.CAPACITY_POLICIES:
                from terralocal.server.domain import rogue_capacity_notices

                capacity_scope = rogue_capacity_notices.in_session(ctx, run)
            closure_scope = None
            if row.policy_version in GIVEUP_POLICIES:
                from terralocal.server.domain import rogue_giveup

                closure_scope = rogue_giveup.validate(run, ctx.session.get(m.RogueRunClosure, run.id),
                                                      rogue_giveup.in_session(ctx, run))
            validate(ctx.data, run, records, children[4], battles, row,
                     visited_scenes(ctx, run), rogue_shops.rows(ctx.session, run.id),
                     layout=in_session(ctx, run), prefix=tuple(prefix), attained=attained, combat_scope=scope,
                     deployment_prefix=tuple(deployments) if row.policy_version in completion_rewards.DEPLOYMENT_POLICIES else None,
                     capacity_scope=capacity_scope, closure_scope=closure_scope)
            if prefix and prefix[-1][1].after != row.before:
                raise invalid()
            prefix.append((run, row))
            if deployment_rules:
                deployments.append(deployment.facts(run, row.facts | {"combat": scope}))
        if history:
            outer = ctx.session.get(m.RogueTopicOuter, (ctx.account_id, "rogue_1"))
            if outer is None or balances(outer.state) != history[-1][1].after:
                raise invalid()
        if deployment_history_out is not None:
            deployment_history_out.extend(deployments)
        if known is not None:
            known.history = history, tuple(deployments)
        return history
    except (DomainError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise invalid() from exc


def settle(ctx):
    from terralocal.server.domain import rogue_runs, rogue_settlement, rogue_shops, rogue_topics
    from terralocal.server.domain.rogue_progress import in_session

    if ctx.local_session is None or ctx.local_session.kind != "game":
        raise DomainError("INVALID_SESSION", "请使用游戏登录确认探索结束", 401)
    rogue_topics._account(ctx)
    run, children = rogue_runs.active(ctx)
    deployment_history = []
    history = history_in_session(ctx, deployment_history_out=deployment_history)
    if run is None:
        latest = ctx.session.scalar(select(m.RogueTopicRun).where(m.RogueTopicRun.account_id == ctx.account_id)
            .order_by(m.RogueTopicRun.created_at.desc(), m.RogueTopicRun.id.desc()).limit(1))
        saved = ctx.session.get(m.RogueGameSettlement, latest.id) if latest is not None else None
        if saved is None:
            raise DomainError("ROGUE_ENDING_NOT_PENDING", "当前没有待确认的探索结束", 409)
        if history and history[-1][1].policy_version in completion_rewards.ORDERED_POLICIES:
            latest, saved = history[-1]
        if not any(previous.id == latest.id and row is saved for previous, row in history):
            raise invalid()
        return deepcopy(saved.response)
    records = rogue_settlement.rows(ctx.session, run.id)
    shops = rogue_shops.rows(ctx.session, run.id)
    battles = ctx.session.scalars(select(m.RogueBattle).where(m.RogueBattle.run_id == run.id)).all()
    scenes = visited_scenes(ctx, run)
    layout = in_session(ctx, run)
    closure = ctx.session.get(m.RogueRunClosure, run.id)
    if closure is not None:
        from terralocal.server.domain import rogue_giveup

        policy = GIVEUP_SCORE_POLICY
        known = rogue_giveup.validate(run, closure, rogue_giveup.in_session(ctx, run))
    else:
        policy = base_policy(records, shops, scenes, layout)
        known = facts(run, records, children[4], battles, scenes, shops, policy=policy, layout=layout, data=ctx.data)
    if completion_available(ctx.data):
        from terralocal.server.domain.rogue_ending_variants import attained_through_run

        selected = (completion_rewards.CAPACITY_POLICY
                    if deployments_available(ctx.data) and capacities_available(ctx.data)
                    else completion_rewards.DEPLOYMENT_POLICY if deployments_available(ctx.data)
                    else completion_rewards.VARIANT_POLICY if variants_available(ctx.data) else completion_rewards.POLICY)
        if closure is not None:
            if selected != completion_rewards.CAPACITY_POLICY:
                raise DomainError("ROGUE_GIVEUP_UNSUPPORTED", "此放弃通知组合尚未接通；保留原探索", 501)
            selected = completion_rewards.GIVEUP_POLICY
        attained = attained_through_run(ctx, run) if selected in completion_rewards.VARIANT_POLICIES else ()
        if selected in completion_rewards.DEPLOYMENT_POLICIES:
            from terralocal.server.domain import rogue_deployment_goals as deployment

            known["combat"] = deployment.in_session(ctx, run, records)
        capacity_scope = None
        if selected in completion_rewards.CAPACITY_POLICIES:
            from terralocal.server.domain import rogue_capacity_notices

            capacity_scope = rogue_capacity_notices.in_session(ctx, run)
        try:
            known["notification"] = completion_rewards.notification(ctx.data, run, known, policy, history,
                policy=selected, attained=attained,
                deployment_prefix=tuple(deployment_history) if selected in completion_rewards.DEPLOYMENT_POLICIES else None,
                capacity_scope=capacity_scope)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise invalid() from exc
        policy = selected
    outer = ctx.session.get(m.RogueTopicOuter, (ctx.account_id, run.topic_id))
    state = rogue_topics.outer_state(outer.state)
    # No unimplemented buff, mission, collection unlock or external grant is
    # silently ignored. Archived first-theme monthly missions are absent.
    if (state["buff"]["unlocked"] or state["buff"]["pointCost"] or state["mission"]["list"]):
        raise DomainError("ROGUE_ENDING_EFFECT_UNSUPPORTED", "此外部效果尚未接入结束结算", 501)
    before = balances(state)
    after, response, rule = calculate(ctx.data, run, known, before, policy=policy)
    at = max(ctx.now, known["ended"])
    settlement = m.RogueGameSettlement(run_id=run.id, policy_version=policy, rule_hash=rule,
        facts=known, before=before, after=after, response=response, created_at=at)
    ctx.session.add(settlement)
    state["bp"]["point"], state["buff"]["pointOwned"] = after["bp"], after["grow"]
    state["record"]["stageCnt"] = after["stages"]
    # The frozen theme explicitly disables public exploration history. The
    # independent result ledger retains failures without inventing a UI list.
    outer.state = state
    if closure is None:
        run.state, run.ended_at = "SETTLED", at
    else:
        run.state = "SETTLED"
    ctx.session.flush()
    from terralocal.server.domain import rogue_banks

    rogue_banks.settle(ctx, run, settlement)
    return response


def preflight(data, path):
    if not path.exists():
        return
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as con:
        con.row_factory = sqlite3.Row
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "rlv2_runs" not in tables:
            return
        if "rlv2_game_settlements" not in tables:
            from terralocal.server.persistence.migrations import (
                CURRENT_REVISIONS,
                ROGUE_ENDING_REVISION,
                ROGUE_SCENE_REVISION,
            )

            current = con.execute("SELECT version_num FROM alembic_version").fetchone()
            if current and current[0] in (*CURRENT_REVISIONS, ROGUE_SCENE_REVISION, ROGUE_ENDING_REVISION):
                raise ValueError(invalid().message)
            return
        try:
            from terralocal.server.domain.rogue_settlement import read_rows

            rows = con.execute("SELECT s.* FROM rlv2_game_settlements s JOIN rlv2_runs r ON s.run_id=r.id "
                               "ORDER BY r.created_at,r.id").fetchall()
            if len(rows) != con.execute("SELECT count(*) FROM rlv2_game_settlements").fetchone()[0]:
                raise invalid()
            entries = []
            for raw in rows:
                row = SimpleNamespace(**dict(raw))
                for key in ("facts", "before", "after", "response"):
                    setattr(row, key, json.loads(getattr(row, key)))
                run = SimpleNamespace(**dict(con.execute("SELECT * FROM rlv2_runs WHERE id=?", (row.run_id,)).fetchone()))
                entries.append((run, row))
            from terralocal.server.domain.rogue_progress import on_disk, read_draft
            from terralocal.server.domain.rogue_shops import read_rows as read_shops
            from terralocal.server.domain.rogue_visits import bind_visited_content
            from terralocal.server.domain.rogue_visits import read_rows as read_scenes

            for key, history in completion_rewards.ordered_groups(entries, LEGACY_POLICIES).items():
                prefix, deployments = [], []
                deployment_rules = deployments_available(data)
                for run, row in history:
                    chars = con.execute("SELECT * FROM rlv2_chars WHERE run_id=?", (run.id,)).fetchall()
                    battles = [SimpleNamespace(**dict(b)) for b in con.execute(
                        "SELECT * FROM rlv2_battles WHERE run_id=?", (run.id,))]
                    from terralocal.server.domain.rogue_ending_variants import attained_on_disk

                    attained = attained_on_disk(data, con, run) if row.policy_version in completion_rewards.VARIANT_POLICIES else None
                    records = read_rows(con, run.id)
                    from terralocal.server.domain import rogue_deployment_goals as deployment

                    scope = deployment.on_disk(data, con, run, records) if deployment_rules else None
                    capacity_scope = None
                    if row.policy_version in completion_rewards.CAPACITY_POLICIES:
                        from terralocal.server.domain import rogue_capacity_notices

                        capacity_scope = rogue_capacity_notices.on_disk(data, con, run)
                    closure_scope = None
                    if row.policy_version in GIVEUP_POLICIES:
                        from terralocal.server.domain import rogue_giveup

                        closure_scope = rogue_giveup.validate(run, rogue_giveup.read_row(con, run.id),
                                                              rogue_giveup.on_disk(data, con, run))
                    draft = read_draft(con, run.id)
                    scenes = bind_visited_content(data, run, draft, read_scenes(con, run.id))
                    validate(data, run, records, chars, battles, row, scenes, read_shops(con, run.id),
                        layout=on_disk(data, con, run, draft), prefix=tuple(prefix), attained=attained, combat_scope=scope,
                        deployment_prefix=tuple(deployments) if row.policy_version in completion_rewards.DEPLOYMENT_POLICIES else None,
                        capacity_scope=capacity_scope, closure_scope=closure_scope)
                    if prefix and prefix[-1][1].after != row.before:
                        raise invalid()
                    prefix.append((run, row))
                    if deployment_rules:
                        deployments.append(deployment.facts(run, row.facts | {"combat": scope}))
                outer = con.execute("SELECT state FROM rlv2_topics WHERE account_id=? AND topic_id=?", key).fetchone()
                if outer is None or balances(json.loads(outer[0])) != history[-1][1].after:
                    raise invalid()
            if con.execute("SELECT 1 FROM rlv2_runs r LEFT JOIN rlv2_game_settlements s ON r.id=s.run_id "
                           "WHERE r.state='SETTLED' AND s.run_id IS NULL LIMIT 1").fetchone():
                raise invalid()
        except (DomainError, ValueError, TypeError, KeyError, AttributeError) as exc:
            raise ValueError(invalid().message) from exc
