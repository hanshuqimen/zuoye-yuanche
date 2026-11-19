"""One reviewed historical capacity condition, not a generic prose parser."""

from dataclasses import dataclass
from types import MappingProxyType

from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.gamedata.rogue_capacity_relics import TARGET
from terralocal.server.gamedata.rogue_roster_unlocks import UnlockProgress
from terralocal.server.gamedata.rogue_roster_unlocks import available as gates_available

POLICY = "rogue1-verified-peak-squad-capacity-unlock-v1"
ITEM = "rogue_1_relic_a40"
DESCRIPTION = "在任意时刻拥有不小于13个可携带干员数"
THRESHOLD = 13


def available(data):
    if not gates_available(data):
        return False
    item = data.table("roguelike_topic_table")["details"]["rogue_1"].get("items", {}).get(ITEM)
    # Older authored profiles with no declared condition stay outside this
    # contract; a declared, changed description is rejected by the compiler.
    return isinstance(item, dict) and item.get("unlockCondDesc") is not None


def invalid():
    return ValueError("首主题历史可携带干员数条件与匹配数据不一致")


@dataclass(frozen=True)
class RunCapacity:
    mode: str
    grade: int
    started_at: int
    peak: int


class FirstThemeCapacityUnlocks:
    def __init__(self, data):
        try:
            detail = data.table("roguelike_topic_table")["details"]["rogue_1"]
            ref = data.rogue_relic_archive.entries[ITEM]
            resource = detail["items"][TARGET]
            if (ref.unlock_description != DESCRIPTION or ref.special or ref.enrollment is not None
                    or detail["gameConst"]["squadCapacityItemId"] != TARGET
                    or resource["id"] != TARGET or resource["type"] != "SQUAD_CAPACITY"):
                raise invalid()
            self.gates = data.rogue_roster_unlocks
        except (KeyError, TypeError, AttributeError) as exc:
            raise invalid() from exc
        self.fingerprint = fingerprint({"policy": POLICY, "data": data.manifest["hash"],
            "archive": data.rogue_relic_archive.fingerprint, "gates": self.gates.fingerprint,
            "item": ITEM, "description": DESCRIPTION, "resource": resource, "threshold": THRESHOLD})

    def evaluate(self, runs):
        if type(runs) is not tuple:
            raise invalid()
        peak = 0
        for run in runs:
            if (type(run) is not RunCapacity or type(run.peak) is not int or not 0 <= run.peak < 2**31):
                raise invalid()
            if self.gates.allows(run.mode, run.grade, run.started_at):
                peak = max(peak, run.peak)
        return MappingProxyType({ITEM: UnlockProgress(min(peak, THRESHOLD), THRESHOLD)})
