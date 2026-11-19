"""Fixed upgrade-ticket scene rewards, separate from random event supply."""

from dataclasses import replace
from types import MappingProxyType

from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.gamedata.rogue_events import LEAVE_DIGEST, Branch, Delta, EventSpec, Frame
from terralocal.server.gamedata.roguelike import invalid

POLICY = "rogue1-fixed-upgrade-event-grant-v1"
SOURCES = (
    ("rogue1-event-upgrade-five-v1", "scene_up1_enter", "choice_up1_1", "scene_up1_1",
     "rogue_1_upgrade_ticket_5star", "66f5190b40bde7f2ab2cf448fb9a253723fd5cf282c682721ce4de6047f4c605"),
    ("rogue1-event-upgrade-all-v1", "scene_up2_enter", "choice_up2_1", "scene_up2_1",
     "rogue_1_upgrade_ticket_all", "d19333e255ef533c2f99285a0f17fa1a3507d600d6810d8e4a6551a884404409"),
)
PROGRAMS = frozenset(row[0] for row in SOURCES)
TICKETS = MappingProxyType({(row[0], row[2]): row[4] for row in SOURCES})


def programs(data):
    catalog, rules = data.rogue_scenes, data.rogue_upgrades
    result = {}
    for key, entry, choice, target, ticket, digest in SOURCES:
        display = data.table("roguelike_topic_table")["details"]["rogue_1"]["choices"].get(choice, {}).get("displayData", {})
        if (not isinstance(display, dict) or ticket not in rules.tickets or choice not in catalog.choices
                or display.get("type") != "ITEM" or display.get("itemId") != ticket
                or catalog.choices[choice].target != target):
            raise invalid("事件进阶券或完整后继场景未匹配")
        spec = EventSpec(key, entry, (
            Frame(entry, (Branch(choice, digest, Delta()),)),
            Frame(target, (Branch("choice_leave", LEAVE_DIGEST, Delta()),))),
            "Frozen complete choice rows and ITEM references; PRTS first-theme event list "
            "fixed five-star/all upgrade tickets: https://prts.wiki/w/傀影与猩红孤钻/事件一览 ; "
            "existing verified free-upgrade and discard flow, no encounter weights or eligibility claim")
        program = catalog.compile(spec)
        # The grant and filter are part of compatibility, beyond graph effects.
        result[key] = replace(program, digest=fingerprint({"policy": POLICY, "graph": program.digest,
            "ticket": ticket, "upgrades": rules.fingerprint}))
    return MappingProxyType(result)
