"""Reviewed dance resource trades; explicit offers, not encounter probabilities.

A prepared offer has three of five trades plus the unconditional escape. The
ten representable subsets do not establish official combination weights or
floor eligibility. Assignment remains a trusted, persisted server decision.
"""

from itertools import combinations
from types import MappingProxyType

from terralocal.server.gamedata.rogue_events import (
    LEAVE_DIGEST,
    Branch,
    Delta,
    EventSpec,
    Frame,
)

SELECTIONS = tuple(combinations(range(1, 6), 3))
PROGRAMS = tuple("rogue1-dance-" + "".join(map(str, values)) + "-v1" for values in SELECTIONS)
ENTRY = "scene_exchange_enter"
# Full frozen choice-row fingerprints, never effect parsing from prose.
RULES = (
    ("choice_exchange_1", "scene_exchange_2",
     "d35e3547931d828979dd0a77cf7fc0b3296f96d942a7a4ac85078712250d61d2",
     Delta(gold=-10, hp=8), (("gold", 10),)),
    ("choice_exchange_2", "scene_exchange_3",
     "82a3ba8410e2b33037c0425485ca3f07911d55c65a68bfea8c7b8ad43958ad09",
     Delta(gold=-10, hope_max=6), (("gold", 10),)),
    ("choice_exchange_3", "scene_exchange_4",
     "48492d441e3034368d13e1fb0075f64746101370be41d8cb92ccec9dac84b057",
     Delta(hope_max=-4, hp=10), (("hope", 4),)),
    ("choice_exchange_4", "scene_exchange_5",
     "e496b448677afc77a12e90df1b078db36a2f5306aa572e24c2234fecaf2d821b",
     Delta(hp=-5, hope_max=8), (("hp", 6),)),
    ("choice_exchange_5", "scene_exchange_6",
     "026ef313c47cd4d220907c8919944f6f9e50dba10a5e0b6be220a322a2b7e452",
     Delta(hp=-5, gold=15), (("hp", 6),)),
)
ESCAPE = ("choice_exchange_6", "scene_exchange_1",
          "39792910f37b1d74bbf21e3f4c671010fd813c8b040c65efbeaade81b5806c43")


def programs(catalog):
    leave = Branch("choice_leave", LEAVE_DIGEST, Delta())
    escape = Branch(ESCAPE[0], ESCAPE[2], Delta())
    result = {}
    for key, selection in zip(PROGRAMS, SELECTIONS, strict=True):
        selected = tuple(RULES[index - 1] for index in selection)
        branches = tuple(Branch(choice, digest, delta, minimum)
                         for choice, _, digest, delta, minimum in selected) + (escape,)
        # Targets are explicit reviewed edges. Checking them here also guards
        # against an authored catalog substituting another graph under a hash.
        edges = tuple((row[0], row[1]) for row in selected) + ((ESCAPE[0], ESCAPE[1]),)
        if any(choice not in catalog.choices or catalog.choices[choice].target != target
               for choice, target in edges):
            from terralocal.server.gamedata.roguelike import invalid

            raise invalid("舞会选择的完整后继场景未匹配")
        frames = (Frame(ENTRY, branches),) + tuple(Frame(target, (leave,)) for _, target in edges)
        spec = EventSpec(key, ENTRY, frames,
            "Frozen complete choice rows and nextSceneId; PRTS IS2 Scarlet Dance effects and "
            "three trades plus escape: https://prts.wiki/w/傀影与猩红孤钻/事件一览 ; "
            "LP spending keeps at least one: https://arknights.wiki.gg/wiki/Life_Point ; "
            "explicit saved subset only, no official subset probabilities, eligibility or modifiers")
        result[key] = catalog.compile(spec)
    return MappingProxyType(result)
