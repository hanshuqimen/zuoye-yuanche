"""Reviewed ordinary-ticket event source; random two-profession offer excluded."""

from dataclasses import replace
from types import MappingProxyType

from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.gamedata.rogue_events import LEAVE_DIGEST, Branch, Delta, EventSpec, Frame
from terralocal.server.gamedata.roguelike import invalid

POLICY = "rogue1-fixed-ordinary-recruit-event-v1"
PROGRAM = "rogue1-event-recruit-all-paid-v1"
PROGRAMS = frozenset({PROGRAM})
ENTRY = "scene_recruit1_enter"
CHOICE = "choice_recruit1_2"
TARGET = "scene_recruit1_2"
TICKET = "rogue_1_recruit_ticket_all"
CHOICE_DIGEST = "3ad33fb0c1a9c786995568da1f1138288aed34da732c8d22ef6d58d30e5a3d43"
EXIT_CHOICE = "choice_recruit1_3"
EXIT_TARGET = "scene_recruit1_3"
EXIT_DIGEST = "aad855ca329e581b55fa61c200cad88bb357bf39107295447175b751b171f495"
TICKETS = MappingProxyType({(PROGRAM, CHOICE): TICKET})


def programs(data):
    catalog, rules = data.rogue_scenes, data.rogue_recruit
    detail = data.table("roguelike_topic_table")["details"]["rogue_1"]
    display = detail["choices"].get(CHOICE, {}).get("displayData")
    if (not isinstance(display, dict) or display.get("type") != "ITEM" or display.get("itemId") != TICKET
            or TICKET not in rules.catalog or CHOICE not in catalog.choices or EXIT_CHOICE not in catalog.choices
            or catalog.choices[CHOICE].target != TARGET or catalog.choices[EXIT_CHOICE].target != EXIT_TARGET):
        raise invalid("普通招募事件的固定券或完整后继未匹配")
    # Costs and candidate ceilings are part of this grant's compatibility.
    # Do not change old programs when introducing this independently admitted
    # source, or silently treat premium/discounted tickets as the plain item.
    spec = EventSpec(PROGRAM, ENTRY, (
        Frame(ENTRY, (Branch(CHOICE, CHOICE_DIGEST, Delta(gold=-5), (("gold", 5),)),
                      Branch(EXIT_CHOICE, EXIT_DIGEST, Delta()))),
        Frame(TARGET, (Branch("choice_leave", LEAVE_DIGEST, Delta()),)),
        Frame(EXIT_TARGET, (Branch("choice_leave", LEAVE_DIGEST, Delta()),))),
        "Complete frozen ITEM/choice rows and PRTS first-theme event list: "
        "https://prts.wiki/w/傀影与猩红孤钻/事件一览 ; fixed five-gold plain all-profession "
        "ticket or narrative exit only. Explicit trusted variant, not the random two-profession "
        "branch, encounter eligibility, weighting or complete event supply.")
    program = catalog.compile(spec)
    digest = fingerprint({"policy": POLICY, "graph": program.digest,
        "ticket": detail["recruitTickets"][TICKET], "item": detail["items"][TICKET],
        "ceiling": detail["detailConst"]["charUpgradeTable"]["0"],
        "recruit_costs": rules.costs, "upgrade_costs": rules.upgrade_costs})
    return MappingProxyType({PROGRAM: replace(program, digest=digest)})
