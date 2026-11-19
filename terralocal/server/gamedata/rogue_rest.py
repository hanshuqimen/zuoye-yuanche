"""IS2 NORMAL/0 rest graph; item effects are completed by the visit driver.

The full frozen choice rows are guarded. This is an explicit base adapter,
not an official node-selection frequency or support for relic modifiers.
"""

from types import MappingProxyType

from terralocal.server.gamedata.rogue_events import LEAVE_DIGEST, Branch, Delta, EventSpec, Frame

PROGRAMS = tuple("rogue1-rest-without-" + str(i) + "-v1" for i in range(1, 5))
PROGRAM = PROGRAMS[3]
UPGRADE_CHOICE = "choice_rest_2"
TICKET = "rogue_1_upgrade_ticket_all"
CHOICES = (
    ("choice_rest_1", "scene_rest_1", Delta(hp=5), "2f44cd9c2fd3f25ea3e2a56045439dbeadeb9900e1ff7179993a1d7f84034a2f"),
    (UPGRADE_CHOICE, "scene_rest_2", Delta(), "b3e7aec3efba597866afc88ed9d1e043cd7702301e8d8754be76c9802951b2bc"),
    ("choice_rest_3", "scene_rest_3", Delta(hope_max=3), "bf65c6a69959d6b130f3cd17843aa20e00495acda140a1e08e4b236b94e063ea"),
    ("choice_rest_4", "scene_rest_4", Delta(squad_capacity=1), "10134936133c48177053d5ceaaaa4951c32899c8ca940ead4f2a220d6a7aea7d"),
)


def programs(data):
    # Admission includes all ten ticket categories and training ceilings, so
    # a rest option can never advertise an item whose promotion is unknown.
    if TICKET not in data.rogue_upgrades.tickets:
        raise ValueError("休整进阶券定义缺失")
    catalog = data.rogue_scenes
    result = {}
    for omitted, program_id in enumerate(PROGRAMS):
        selected = tuple(row for i, row in enumerate(CHOICES) if i != omitted)
        spec = EventSpec(program_id, "scene_rest_enter", (
            Frame("scene_rest_enter", tuple(Branch(choice, digest, delta) for choice, _, delta, digest in selected)),
            *(Frame(scene, (Branch("choice_leave", LEAVE_DIGEST, Delta()),)) for _, scene, _, _ in selected)),
            "Frozen CN2.7.71 IS2 complete rest choice rows/nextSceneId/item references; "
            "base effects HP5, free upgrade ticket, hope3, carry1. "
            "PRTS IS2 event-node description specifies three available benefits: "
            "https://prts.wiki/w/傀影与猩红孤钻#事件节点 . "
            "GetUpgradableCharCount default eligibility: rarity>=four, upgradePhase0, ticket masks. "
            "Explicit saved three-choice set; no inferred official selection weights or relic-modifier claim.")
        result[program_id] = catalog.compile(spec)
    return MappingProxyType(result)
