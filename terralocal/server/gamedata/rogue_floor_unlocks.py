"""Three unconditional floor-clear relic goals from the matched first theme.

Only validated completed-floor transitions count. Entering a floor, preparing
maps, defeating an ordinary enemy or ending/abandoning a run grants no floor.
Conditional floor goals, bands and successful endings have separate rules.
"""

from dataclasses import dataclass
from types import MappingProxyType

from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.gamedata.rogue_roster_unlocks import UnlockProgress
from terralocal.server.gamedata.rogue_roster_unlocks import available as roster_available

POLICY = "rogue1-unconditional-floor-relic-unlocks-v1"
ZONES = ("迷雾歧途", "落阳庭院", "故土残躯", "噩梦之始")
CONDITIONS = {
    "rogue_1_relic_r25": (1, "通过第一层【迷雾歧途】"),
    "rogue_1_relic_a48": (2, "通过第二层【落阳庭院】"),
    "rogue_1_relic_a34": (4, "通过第四层【噩梦之始】"),
}


def available(data):
    if not roster_available(data):
        return False
    # Historical QA catalogs omit named regions and declare no such contract.
    # Any declared name (including malformed names) enables strict admission.
    zones = data.table("roguelike_topic_table")["details"]["rogue_1"].get("zones", {})
    return type(zones) is not dict or any(type(v) is not dict or "name" in v for v in zones.values())


def invalid():
    return ValueError("首主题过层收藏品条件或区域与匹配数据不一致")


@dataclass(frozen=True)
class RunFloors:
    mode: str
    grade: int
    started_at: int
    completed: tuple[str, ...]


class FirstThemeFloorUnlocks:
    def __init__(self, data):
        try:
            detail = data.table("roguelike_topic_table")["details"]["rogue_1"]
            self.gates = data.rogue_roster_unlocks
            for number, name in enumerate(ZONES, 1):
                key = "zone_" + str(number)
                zone = detail["zones"][key]
                if zone["id"] != key or zone["name"] != name or zone["isHiddenZone"] is not False:
                    raise invalid()
                data.rogue_map.require_zone(key)
            for key, (_, description) in CONDITIONS.items():
                row = data.rogue_relic_archive.entries[key]
                if row.unlock_description != description or row.enrollment is not None or row.special:
                    raise invalid()
        except (KeyError, TypeError, AttributeError) as exc:
            raise invalid() from exc
        self.conditions = MappingProxyType(dict(CONDITIONS))
        self.fingerprint = fingerprint({"policy": POLICY, "data": data.manifest["hash"],
            "archive": data.rogue_relic_archive.fingerprint, "gates": self.gates.fingerprint,
            "conditions": dict(self.conditions), "zones": ZONES})

    def evaluate(self, runs):
        if type(runs) is not tuple:
            raise invalid()
        completed = 0
        for run in runs:
            if (type(run) is not RunFloors or type(run.completed) is not tuple or len(run.completed) > 15
                    or any(type(z) is not str or not 0 < len(z) <= 128 for z in run.completed)):
                raise invalid()
            allowed = self.gates.allows(run.mode, run.grade, run.started_at)
            # Explicit local recipes may repeat or reorder regions. They are
            # playable recipes, not proof of completing canonical floor N.
            prefix = 0
            for number, zone in enumerate(run.completed, 1):
                if zone != "zone_" + str(number):
                    break
                prefix = number
            if allowed:
                completed = max(completed, prefix)
        return MappingProxyType({key: UnlockProgress(int(completed >= target), 1)
            for key, (target, _) in self.conditions.items()})
