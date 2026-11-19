"""Versioned base NORMAL/0 default final-boss outcome and ending facts.

Only the canonical five-floor default route is enabled here. Hidden routes,
elite reward selection and route-relic acquisition are separate work. Terminal
base XP/gold uses the existing regional adapter, with no invented relic pool.
"""

from dataclasses import asdict

from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_map import Point
from terralocal.server.domain.rogue_progress import Layout, row_index
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.gamedata.rogue_battle_effects import supported
from terralocal.server.gamedata.rogue_capacity_relics import supported as capacity_supported
from terralocal.server.gamedata.rogue_currency_relics import supported as currency_supported
from terralocal.server.gamedata.rogue_gold_relics import supported as gold_supported
from terralocal.server.gamedata.rogue_life_relics import supported as life_supported
from terralocal.server.gamedata.rogue_recruit_costs import FILTERS
from terralocal.server.gamedata.rogue_resource_relics import supported as resource_supported
from terralocal.server.gamedata.rogue_rewards import FirstThemeBattleRewards

POLICY = "rogue1-normal0-default-terminal-boss-v3"
ENDING_POLICY = "rogue1-normal0-default-boss-ending-v6"


def unsupported():
    return DomainError("ROGUE_BOSS_BRANCH", "此Boss分歧、楼层或效果尚未接通；原探索保留", 501)


def validate(data, run, battle, layout, relics):
    def admitted(key):
        if type(key) is not str:
            return False
        try:
            return (key in FILTERS or supported(data, key) or capacity_supported(data, key)
                    or gold_supported(data, key) or resource_supported(data, key) or currency_supported(data, key)
                    or life_supported(data, key))
        except ValueError as exc:
            # A changed definition is still an unsupported battle branch;
            # preserve the existing outcome instead of leaking a raw error.
            raise unsupported() from exc

    if (run.topic_id != "rogue_1" or run.mode != "NORMAL" or run.grade != 0
            or run.band_id != data.rogue_initial.band or not isinstance(layout, Layout)
            or layout.index != 5 or len(layout.zones) != 5 or len(layout.journal) != 4
            or tuple(z.id for z in layout.zones) != tuple("zone_" + str(i) for i in range(1, 6))
            or row_index(battle) != 5 or battle.stage_id != "ro1_b_6"
            or type(relics) is not tuple or any(not admitted(key) for key in relics)):
        raise unsupported()
    point = Point(battle.node_x, battle.node_y)
    node = next((n for n in layout.current.nodes if n.pos == point), None)
    if node is None or node.kind != "BATTLE_BOSS" or node.stage != battle.stage_id or node.next:
        raise unsupported()
    route = data.rogue_endings.cleared(battle.stage_id, layout.id, relics)
    if route.ending != "ro_ending_1" or route.next_zone is not None:
        raise unsupported()
    return route


def compute(data, run, battle, zone, kind, before, facts, *, layout, relics, exp_multiplier=1, capsule_proof=None):
    route = validate(data, run, battle, layout, relics)
    if kind != "BATTLE_BOSS" or zone != "zone_5" or before["shield"] != 0 or before["hp"] <= 0:
        raise unsupported()
    base = FirstThemeBattleRewards(data).base(topic=run.topic_id, mode=run.mode, grade=run.grade,
        zone=zone, kind=kind, stage=battle.stage_id)
    zero = dict.fromkeys(("exp", "populationMax", "squadCapacity", "hp", "shield", "maxHpUp"), 0)
    defeated = (facts["rank"] == 1 and facts["leftHp"] == 0 and 0 <= facts["percent"] <= 100)
    total = before["hp"] + data.rogue_initial.battle_temporary_hp
    perfect = facts["rank"] == 3 and facts["leftHp"] == total
    damaged = facts["rank"] == 2 and 0 < facts["leftHp"] < total
    if facts["interrupt"] or facts["giveUp"] or not (defeated or (perfect or damaged) and facts["percent"] == 100):
        raise unsupported()
    if defeated:
        after, earn, outcome, ending = before | {"hp": 0}, zero, "DEFEAT", None
    else:
        exp = base.exp * exp_multiplier
        gain = data.rogue_levels.gains(before["exp"], before["exp"] + exp)
        if gain.max_hp or gain.battle_char_limit:
            raise unsupported()
        after = before | {"hp": min(before["hp"], facts["leftHp"]), "gold": before["gold"] + base.gold,
            "exp": before["exp"] + exp, "level": gain.to_level,
            "hope_max": before["hope_max"] + gain.hope_max,
            "squad_capacity": before["squad_capacity"] + gain.squad_capacity}
        if any(type(v) is not int or not 0 <= v < 2**31 for v in after.values()):
            raise unsupported()
        earn = zero | {"exp": exp, "populationMax": gain.hope_max,
            "squadCapacity": gain.squad_capacity, "hp": after["hp"] - before["hp"]}
        outcome, ending = "SUCCESS", route.ending
    rule = fingerprint({"policy": POLICY, "base": base.rule_hash, "endings": data.rogue_endings.fingerprint,
        "levels": data.rogue_levels.fingerprint, "band": run.band_id,
        "temporary_hp": data.rogue_initial.battle_temporary_hp, "outcome": outcome} | (capsule_proof or {}))
    return {"zone": zone, "kind": kind, "before": before, "after": after, "earn": earn,
            "outcome": outcome, "ending": ending, "isPerfect": bool(not defeated and perfect)}, [], rule


def ending_facts(data, run, records, chars, battles, scenes, shops, layout):
    from terralocal.server.domain.rogue_ending import collected_relics
    from terralocal.server.domain.rogue_settlement import LOOT_POLICY

    if not records or not isinstance(layout, Layout):
        raise unsupported()
    by_id = {b.id: b for b in battles}
    final = records[-1]
    if (set(by_id) != {r.battle_id for r in records} or final.policy_version != POLICY
            or final.effects.get("outcome") not in ("SUCCESS", "DEFEAT") or final.completed_at is not None
            or any(r.effects.get("outcome") == "DEFEAT" or r.completed_at is None
                   or r.effects["kind"] not in ("BATTLE_NORMAL", "BATTLE_ELITE", "BATTLE_BOSS")
                   or r.effects["kind"] != "BATTLE_NORMAL" and r.policy_version != LOOT_POLICY
                   for r in records[:-1])):
        raise unsupported()
    validate(data, run, by_id[final.battle_id], layout, ())
    success = final.effects["outcome"] == "SUCCESS"
    if (run.hp == 0) == success or final.effects.get("ending") != ("ro_ending_1" if success else None):
        raise unsupported()
    entered = [s for s in scenes if s.state != "PREPARED"]
    traded = [s for s in shops if s.state != "PREPARED"]
    if any(s.state != "FINISHED" or type(s.ended_at) is not int
           or not run.created_at <= s.ended_at <= final.created_at for s in (*entered, *traded)):
        raise unsupported()
    stages = {}
    for row in records:
        if row.effects.get("outcome") == "DEFEAT":
            continue
        stage = by_id[row.battle_id].stage_id
        stages[stage] = stages.get(stage, 0) + 1
    return {"counts": [4 + int(success), len(records) + len(entered) + len(traded),
                sum(r.effects["kind"] == "BATTLE_NORMAL" for r in records[:-1]),
                sum(r.effects["kind"] == "BATTLE_ELITE" for r in records[:-1]),
                sum(r.effects["kind"] == "BATTLE_BOSS" for r in records[:-1]) + int(success),
                collected_relics(shops, scenes, records), len(chars)],
        "stages": stages, "ended": final.created_at, "success": int(success),
        "ending": "ro_ending_1" if success else None,
        "battles": [[r.battle_id, r.rule_hash, fingerprint(r.facts)] for r in records],
        "scenes": [[s.id, s.rule_hash, fingerprint({"before": s.before, "steps": s.steps,
            "recruits": s.recruit_count, "entered": s.entered_at, "ended": s.ended_at})] for s in entered],
        "shops": [[s.id, s.rule_hash, fingerprint({"before": s.before, "first_ticket": s.first_ticket,
            "purchases": s.purchases, "entered": s.entered_at, "ended": s.ended_at})] for s in traded],
        "floors": {"index": layout.index, "journal": [asdict(t) for t in layout.journal],
            "maps": [fingerprint(z.wire()) for z in layout.zones]}}
