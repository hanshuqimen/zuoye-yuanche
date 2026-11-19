"""Twenty explicitly matched completion goals, not a prose rule parser.

The frozen item conditions define this finite adapter. REA establishes the
archive state/progress consumer, not official server predicates or drop pools.
"""

from dataclasses import dataclass
from types import MappingProxyType

from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.gamedata.rogue_roster_unlocks import UnlockProgress
from terralocal.server.gamedata.rogue_roster_unlocks import available as roster_available

POLICY = "rogue1-completion-only-relic-goals-v1"
CONDITIONS = {
    **{"rogue_1_relic_c" + str(i).zfill(2): (
        "完成游戏结局", None if i < 7 else "rogue_1_enroll_3") for i in range(1, 13)},
    **{"rogue_1_relic_m" + str(i): ("完成游戏结局", None) for i in (10, 11, 12, 16, 17, 18)},
    **{"rogue_1_relic_n" + str(i).zfill(2): (
        "【内容拓展 · 二】后，完成一次游戏结局", "rogue_1_enroll_2") for i in (1, 2)},
}


def available(data):
    if not roster_available(data):
        return False
    detail = data.table("roguelike_topic_table")["details"]["rogue_1"]
    archive = detail
    for key in ("archiveComp", "relic", "relic"):
        if type(archive) is not dict:
            return True
        archive = archive.get(key, {})
    # Older QA catalogs with no declared completion-goal entries stay on their
    # previous capability. Any declaration enables strict whole-family checks.
    return type(archive) is not dict or bool(set(archive) & CONDITIONS.keys())


def invalid():
    return ValueError("首主题结局收藏品条件、登记或成功事实与匹配数据不一致")


@dataclass(frozen=True)
class RunCompletion:
    mode: str
    grade: int
    started_at: int
    ended_at: int
    success: int
    ending: str | None


class FirstThemeEndingUnlocks:
    def __init__(self, data):
        self.gates = data.rogue_roster_unlocks
        enrolled = {}
        try:
            detail = data.table("roguelike_topic_table")["details"]["rogue_1"]
            for key, (description, enrollment) in CONDITIONS.items():
                entry = data.rogue_relic_archive.entries[key]
                if (entry.unlock_description != description or entry.enrollment != enrollment or entry.special):
                    raise invalid()
                at = 0
                if enrollment is not None:
                    row = detail["enrolls"][enrollment]
                    at = row["enrollTime"]
                    if (row["enrollId"] != enrollment or type(at) is not int or not 0 <= at < 2**63
                            or row["enrollType"] != ("DLC" if enrollment.endswith("_2") else "REVIEW")):
                        raise invalid()
                enrolled[key] = at
            self.endings = frozenset(row[2] for row in data.rogue_endings.finals.values())
            if self.endings != {"ro_ending_" + str(i) for i in range(1, 5)}:
                raise invalid()
        except (KeyError, TypeError, AttributeError) as exc:
            raise invalid() from exc
        self.enrolled = MappingProxyType(enrolled)
        self.conditions = MappingProxyType(dict(CONDITIONS))
        self.fingerprint = fingerprint({"policy": POLICY, "data": data.manifest["hash"],
            "archive": data.rogue_relic_archive.fingerprint, "gates": self.gates.fingerprint,
            "endings": data.rogue_endings.fingerprint, "conditions": dict(self.conditions),
            "enrolled": enrolled})

    def evaluate(self, runs):
        if type(runs) is not tuple:
            raise invalid()
        latest = -1
        for run in runs:
            if (type(run) is not RunCompletion or type(run.started_at) is not int
                    or type(run.ended_at) is not int or not 0 <= run.started_at <= run.ended_at < 2**63
                    or type(run.success) is not int or run.success not in (0, 1)
                    or (type(run.ending) is not str or run.ending not in self.endings
                        if run.success else run.ending is not None)):
                raise invalid()
            allowed = self.gates.allows(run.mode, run.grade, run.started_at)
            if allowed and run.success:
                latest = max(latest, run.ended_at)
        # Eligibility is binary and non-consumable. It never grants an item,
        # an inventory layer, a branch node, or a natural supply entry.
        return MappingProxyType({key: UnlockProgress(int(latest >= at), 1)
                                 for key, at in self.enrolled.items()})
