"""Two matched first-theme completion goals, using proven deployment minima.

SPAWN is the client's post-ignoreCharStats counter, not a journal-row count.
Missing older counters remain unknown; a proven minimum can still establish
an inclusive threshold. Independent explorations never add their counts.
"""

from dataclasses import dataclass
from types import MappingProxyType

from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.gamedata.rogue_ending_unlocks import RunCompletion
from terralocal.server.gamedata.rogue_ending_variants import available as variants_available
from terralocal.server.gamedata.rogue_roster_unlocks import UnlockProgress

POLICY = "rogue1-deployment-completion-goals-v1"
MEASURE = "sum-of-bound-battle-SPAWN-lower-bound-v1"
MAX_DEPLOYMENTS = 512 * 100_000  # Existing local battle/codec budgets, not official limits.
GOALS = {
    "rogue_1_relic_sp02": ("近卫军帽", 200, 2, "PCS02"),
    "rogue_1_relic_sp04": ("古堡的子嗣", 100, 4, "PCS04"),
}


def available(data):
    if not variants_available(data):
        return False
    archive = data.table("roguelike_topic_table")["details"]["rogue_1"]
    for key in ("archiveComp", "relic", "relic"):
        if type(archive) is not dict:
            return True
        archive = archive.get(key, {})
    return type(archive) is not dict or bool(set(archive) & GOALS.keys())


def invalid():
    return ValueError("首主题部署通关条件、特殊图鉴身份或战斗计数不一致")


@dataclass(frozen=True)
class RunDeployment:
    id: str
    completion: RunCompletion
    minimum: int
    unknown: int


class FirstThemeDeploymentGoals:
    def __init__(self, data):
        self.base = data.rogue_ending_unlocks
        try:
            detail = data.table("roguelike_topic_table")["details"]["rogue_1"]
            for key, (name, threshold, sort, order) in GOALS.items():
                item, entry = detail["items"][key], data.rogue_relic_archive.entries[key]
                if (item.get("name") != name or entry.enrollment is not None or not entry.special
                        or (entry.group, entry.sort, entry.order) != (7, sort, order)
                        or entry.unlock_description != f"累计在战斗中部署干员不小于{threshold}次的情况下完成游戏结局"):
                    raise invalid()
        except (KeyError, TypeError, AttributeError) as exc:
            raise invalid() from exc
        self.conditions = MappingProxyType(dict(GOALS))
        self.fingerprint = fingerprint({"policy": POLICY, "measure": MEASURE, "data": data.manifest["hash"],
            "archive": data.rogue_relic_archive.fingerprint, "completion": self.base.fingerprint, "goals": GOALS})

    def evaluate(self, runs):
        if type(runs) is not tuple or any(type(run) is not RunDeployment for run in runs):
            raise invalid()
        self.base.evaluate(tuple(run.completion for run in runs))
        seen, qualified = set(), set()
        for run in runs:
            if (type(run.id) is not str or not 0 < len(run.id) <= 128 or run.id in seen
                    or type(run.minimum) is not int or not 0 <= run.minimum <= MAX_DEPLOYMENTS
                    or type(run.unknown) is not int or not 0 <= run.unknown <= 512):
                raise invalid()
            seen.add(run.id)
            completed = run.completion
            if completed.success and self.base.gates.allows(completed.mode, completed.grade, completed.started_at):
                qualified.update(key for key, (_, threshold, _, _) in GOALS.items() if run.minimum >= threshold)
        return MappingProxyType({key: UnlockProgress(int(key in qualified), 1) for key in GOALS})
