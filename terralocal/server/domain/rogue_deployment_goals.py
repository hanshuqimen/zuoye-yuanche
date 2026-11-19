"""Read only selected archives from owned battles in their settlement order."""

import json

from sqlalchemy import func, select

from terralocal.server.domain import rogue_combat_records
from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.rogue_deployment_goals import RunDeployment
from terralocal.server.gamedata.rogue_ending_unlocks import RunCompletion
from terralocal.server.persistence import models as m

POLICY = "rogue1-owned-deployment-scope-v1"


def invalid():
    return DomainError("ROGUE_DEPLOYMENT_GOAL_INCOMPATIBLE", "部署通关条件与已归属战斗记录不一致；请保留原存档", 503)


def _scope(data, run, records, sources):
    try:
        if (run.topic_id != "rogue_1" or run.gamedata_hash != data.manifest["hash"] or len(records) > 512
                or [r.ordinal for r in records] != list(range(len(records)))
                or [r.battle_id for r in records] != [s[0] for s in sources]):
            raise invalid()
        minimum, unknown, proof = 0, 0, []
        for record, (battle, owner, run_id, data_hash, state, kind, encoded) in zip(records, sources, strict=True):
            if (record.run_id != run.id or owner != run.account_id or run_id != run.id
                    or data_hash != run.gamedata_hash or state != "FINISHED"):
                raise invalid()
            if kind is None:
                unknown += 1
                proof.append([battle, None])
                continue
            if kind != "object" or type(encoded) is not str:
                raise invalid()
            value = json.loads(encoded)
            counters = rogue_combat_records.read(value, battle_id=battle, run_id=run.id,
                                                  gamedata_hash=data_hash, facts=record.facts)
            # The client already excludes ignoreCharStats. No guessed roster
            # or predefined-unit filter is imposed on that post-filter pool.
            minimum += counters.spawns
            proof.append([battle, value["hash"]])
        return {"policy": POLICY, "minimum": minimum, "unknown": unknown, "battles": proof}
    except (DomainError, TypeError, ValueError, KeyError, AttributeError) as exc:
        raise invalid() from exc


def in_session(ctx, run, records):
    ctx.session.flush()
    s, b = m.RogueBattleSettlement, m.RogueBattle
    sources = ctx.session.execute(select(b.id, b.account_id, b.run_id, b.gamedata_hash, b.state,
        func.json_type(s.records, "$.counters"), func.json_extract(s.records, "$.counters"))
        .join(s, s.battle_id == b.id).where(s.run_id == run.id).order_by(s.ordinal)).all()
    return _scope(ctx.data, run, records, sources)


def on_disk(data, con, run, records):
    sources = con.execute("SELECT b.id,b.account_id,b.run_id,b.gamedata_hash,b.state,"
        "json_type(s.records,'$.counters'),json_extract(s.records,'$.counters') "
        "FROM rlv2_battle_settlements s JOIN rlv2_battles b ON s.battle_id=b.id "
        "WHERE s.run_id=? ORDER BY s.ordinal", (run.id,)).fetchall()
    return _scope(data, run, records, sources)


def facts(run, known):
    scope = known["combat"]
    if (type(scope) is not dict or set(scope) != {"policy", "minimum", "unknown", "battles"}
            or scope["policy"] != POLICY):
        raise invalid()
    return RunDeployment(run.id, RunCompletion(run.mode, run.grade, run.created_at, known["ended"],
        known.get("success", 0), known.get("ending")), scope["minimum"], scope["unknown"])
