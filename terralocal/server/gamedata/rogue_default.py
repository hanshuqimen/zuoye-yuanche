"""Versioned playable IS2 base supply for one frozen import.

Regional membership, complete effects and intrinsic eligibility have separate
reviewed adapters. Layout mixtures, equal relic draws, four stock slots and
ticket/tool prices below are explicit TerraLocal policy, NOT recovered official
spawn/merchant rules. This is an incremental base profile, not a complete theme.
The full concrete source is frozen in each new run; old maps never call this.
"""

import json
import random
from dataclasses import asdict

from terralocal.server.compatibility.profile import ROGUE_DATA_HASH
from terralocal.server.domain.rogue_map import Column, Entry, Plan
from terralocal.server.gamedata.repository import canonical, fingerprint
from terralocal.server.gamedata.rogue_base_relics import SOURCES
from terralocal.server.gamedata.rogue_content_specs import TYPED_POLICY
from terralocal.server.gamedata.rogue_placements import BOSSES, NORMALS
from terralocal.server.gamedata.rogue_rest import PROGRAMS as REST_PROGRAMS
from terralocal.server.gamedata.rogue_support_tools import SOURCES as TOOLS
from terralocal.server.gamedata.rogue_treasures import POLICY as TREASURE_POLICY

POLICY = "terralocal-is2-playable-base-supply-v1"
REFERENCE = "https://prts.wiki/w/傀影与猩红孤钻"
# Unverified normal merchant terms, deliberately named local instead of being
# inferred from a relic's rarity, a QA quote, or another IS theme.
LOCAL_TICKET_PRICE, LOCAL_TOOL_PRICE = 4, 4
TICKET_CLASSES = ("pioneer", "warrior", "tank", "sniper", "caster", "medic", "support", "special")
FIRST_TICKET_CLASSES = ("pioneer", "caster", "medic")


def invalid():
    return ValueError("首主题本地基础供给与冻结版本、开放资格或完整内容不匹配")


def source(data, run, owned):
    """Trusted new-run source only; no table/claim/client-driven fallback pool."""
    if (data.manifest["hash"] != ROGUE_DATA_HASH or run.topic_id != "rogue_1"
            or run.mode != "NORMAL" or run.grade != 0):
        return None
    if (type(run.grade) is not int or type(run.seed) is not int or not 0 <= run.seed < 2**63
            or type(owned) is not frozenset or any(type(key) is not str for key in owned)
            or run.gamedata_hash != data.manifest["hash"]):
        raise invalid()
    topic = data.rogue_topics.topic(run.topic_id, at=run.created_at)
    if not topic.started(run.created_at):
        raise invalid()
    base = data.rogue_base_relics
    opened = base.evaluate(run.created_at)
    # Only the per-ID reviewed intrinsic set. Other unlocked/seen archive rows
    # do not silently become an ordinary drop pool or merchant qualification.
    relics = sorted(key for key in SOURCES if opened[key].opened and key not in owned)
    if len(relics) < 14:
        raise invalid()
    identity = {"policy": POLICY, "data": data.manifest["hash"], "run": run.id,
                "account": run.account_id, "seed": run.seed, "at": run.created_at,
                "base_availability": base.fingerprint, "eligible": relics, "owned": sorted(owned)}
    scope = fingerprint(identity)
    rng = random.Random(int(scope, 16))
    rng.shuffle(relics)
    # Disjoint finite budgets keep all branches publishable under the existing
    # nonstack journal contract. No greedy exhaustion, retries or trimmed menu.
    shops = (relics[0:2], relics[2:4], relics[4:6])
    treasures, middle, elite = relics[6:8], relics[8:11], relics[11:14]
    normal = tuple(relics[14 + i::5] for i in range(5))
    tools = sorted(TOOLS)
    rng.shuffle(tools)
    tools = tools[:3]
    if len(tools) != 3:
        raise invalid()
    for key in tools:
        data.rogue_support_tools.require(key, run.created_at)
    evidence = (POLICY + "; scope=" + scope + "; " + REFERENCE
                + "; reviewed regional IDs, intrinsic relic eligibility and complete effects; "
                "local layout/weights/stock and ticket/tool prices, not official distribution; "
                "partial base content, no hidden endings/hallucinations/complete event pool")

    def entry(kind, stage=None, weight=1):
        return Entry(kind, weight, stage)

    def column(pool, minimum=1, maximum=3):
        return Column(minimum, maximum, tuple(pool))

    floors, supplies = [], []
    for number in range(1, 6):
        zone = "zone_" + str(number)
        ordinary = tuple(entry("BATTLE_NORMAL", key, 4) for key in NORMALS[zone])
        # Category totals are explicit local weights independent of stage count.
        mixed = ordinary + (entry("INCIDENT", weight=len(ordinary) * 2),
                            entry("REST", weight=len(ordinary)))
        incident = column((entry("INCIDENT"),), 2, 3)
        rest = column((entry("REST"),), 1, 1)
        shop = column((entry("SHOP"),), 1, 1)
        treasure = column((entry("TREASURE"),), 1, 1)
        if number == 1:
            columns = (column(ordinary, 1, 1), incident, column(mixed), shop)
        elif number == 2:
            columns = (column(mixed), column(mixed), column(mixed), column(mixed), treasure)
        elif number == 3:
            columns = (column(mixed), column(mixed), shop, column(mixed), rest,
                       column(tuple(entry("BATTLE_BOSS", key) for key in BOSSES[zone]), 1, 1))
        elif number == 4:
            elites = tuple(entry("BATTLE_ELITE", data.rogue_map.emergency_variants[key]) for key in NORMALS[zone])
            columns = (column(mixed), column(mixed), column(elites, 1, 1), column(mixed), rest, treasure)
        else:
            columns = (column(mixed), column(mixed), column(mixed), shop, column(mixed), rest,
                       column((entry("BATTLE_BOSS", "ro1_b_6"),), 1, 1))
        floors.append(asdict(Plan(zone, columns, 1500)))
        supply = {role: [] for role in ("incident", "rest", "shop", "battle", "treasure", "recreation")}

        def candidate(key, content, weight=1):
            return {"id": key, "weight": weight, "content": content}

        supply["incident"] = [candidate(key, {"program": key})
                              for key in ("rogue1-fixed-hp", "rogue1-fixed-hope", "rogue1-fixed-gold")]
        supply["rest"] = [candidate(key, {"program": key}) for key in REST_PROGRAMS]
        supply["battle"] = [candidate("base", {"groups": [], "eligibility": [], "base_only": True,
                              "kinds": ["BATTLE_NORMAL"], "evidence": evidence}, 9)]
        for key in normal[number - 1]:
            supply["battle"].append(candidate(key, {"groups": [[key]], "eligibility": [key],
                "kinds": ["BATTLE_NORMAL"], "evidence": evidence}))
        if number in (3, 4):
            keys = middle if number == 3 else elite
            supply["battle"].append(candidate("three-choice", {"groups": [keys], "eligibility": keys,
                "kinds": ["BATTLE_BOSS" if number == 3 else "BATTLE_ELITE"], "evidence": evidence}))
        if number in (2, 4):
            key = treasures[0 if number == 2 else 1]
            supply["treasure"] = [candidate("history", {"schema": 1, "policy": TREASURE_POLICY,
                "variant": "history", "rewards": [{"choice": "choice_treasure1_1", "item": key}],
                "eligibility": [key], "evidence": evidence})]
        if number in (1, 3, 5):
            shop_index = (number - 1) // 2
            classes = FIRST_TICKET_CLASSES if number == 1 else TICKET_CLASSES
            ticket = "rogue_1_recruit_ticket_" + rng.choice(classes)
            if ticket not in data.rogue_recruit.catalog:
                raise invalid()
            terms = [data.rogue_merchant_relics.offer("relic-" + str(i), key,
                topic=run.topic_id, mode=run.mode, grade=run.grade, at=run.created_at,
                collection_state=1, owned=False) for i, key in enumerate(shops[shop_index])]
            offers = [{"index": o.index, "item_id": o.item_id, "price": o.price, "relic_layer": o.relic_layer}
                      for o in terms]
            offers += [{"index": "ticket", "item_id": ticket, "price": LOCAL_TICKET_PRICE},
                       {"index": "tool", "item_id": tools[shop_index], "price": LOCAL_TOOL_PRICE}]
            supply["shop"] = [candidate("shop", {"id": POLICY + "-" + str(number),
                                                     "offers": offers, "evidence": evidence})]
        supplies.append(supply)
    return json.loads(canonical({"schema": 1, "policy": TYPED_POLICY, "theme": "rogue_1", "mode": "NORMAL", "grade": 0,
            "gamedata_hash": data.manifest["hash"], "evidence": evidence, "floors": floors, "supplies": supplies}))
