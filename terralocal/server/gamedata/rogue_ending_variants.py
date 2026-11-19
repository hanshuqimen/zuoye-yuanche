"""Fourteen exact first-theme conditional completion goals.

This is a finite matched-table adapter, not a natural band/item supply pool.
The three cumulative deployment/life-loss goals are deliberately separate.
"""

from dataclasses import dataclass
from types import MappingProxyType

from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.gamedata.rogue_ending_unlocks import RunCompletion
from terralocal.server.gamedata.rogue_ending_unlocks import available as endings_available
from terralocal.server.gamedata.rogue_recruit_costs import FILTERS
from terralocal.server.gamedata.rogue_roster_unlocks import UnlockProgress

POLICY = "rogue1-fourteen-ending-variant-goals-v1"
BANDS = {
    "rogue_1_band_1": "指挥分队", "rogue_1_band_2": "集群分队", "rogue_1_band_3": "后勤分队",
    "rogue_1_band_4": "矛头分队", "rogue_1_band_5": "突击战术分队", "rogue_1_band_6": "堡垒战术分队",
    "rogue_1_band_7": "远程战术分队", "rogue_1_band_8": "破坏战术分队", "rogue_1_band_9": "研究分队",
    "rogue_1_band_10": "高规格分队",
}
BAND_GOALS = {
    "rogue_1_relic_" + relic: "rogue_1_band_" + str(band)
    for relic, band in (("a03", 1), ("a06", 2), ("r12", 3), ("a12", 4), ("a21", 5),
                        ("a24", 6), ("q15", 7), ("q19", 8), ("a27", 9), ("a08", 10))
}
THRESHOLDS = {
    "rogue_1_relic_q05": ("hope_left", 8, "剩余不小于8点希望时完成游戏结局"),
    "rogue_1_relic_q06": ("hope_max", 60, "拥有不小于60点以上希望上限时完成游戏结局"),
    "rogue_1_relic_r28": ("characters", 15, "拥有不小于15名干员时完成游戏结局"),
    "rogue_1_relic_r32": ("gold", 50, "剩余不小于50源石锭时完成游戏结局"),
}
CONDITIONS = {key: "选择【" + BANDS[band] + "】完成游戏结局" for key, band in BAND_GOALS.items()}
CONDITIONS.update({key: value[2] for key, value in THRESHOLDS.items()})


def available(data):
    if not endings_available(data):
        return False
    archive = data.table("roguelike_topic_table")["details"]["rogue_1"]
    for key in ("archiveComp", "relic", "relic"):
        if type(archive) is not dict:
            return True
        archive = archive.get(key, {})
    # R28 already belongs to the older four-item acquisition adapter. Its
    # presence alone does not declare this additional completion capability.
    return type(archive) is not dict or bool(set(archive) & (CONDITIONS.keys() - FILTERS.keys()))


def invalid():
    return ValueError("首主题通关附加条件、分队或结束属性与匹配数据不一致")


@dataclass(frozen=True)
class RunEndingVariant:
    completion: RunCompletion
    band: str
    hope_left: int
    hope_max: int
    characters: int
    gold: int


class FirstThemeEndingVariants:
    def __init__(self, data):
        self.base = data.rogue_ending_unlocks
        try:
            detail = data.table("roguelike_topic_table")["details"]["rogue_1"]
            for key, name in BANDS.items():
                band = detail["items"][key]
                if band.get("id") != key or band.get("type") != "BAND" or band.get("name") != name:
                    raise invalid()
            for key, description in CONDITIONS.items():
                entry = data.rogue_relic_archive.entries[key]
                if entry.unlock_description != description or entry.enrollment is not None or entry.special:
                    raise invalid()
        except (KeyError, TypeError, AttributeError) as exc:
            raise invalid() from exc
        self.conditions = MappingProxyType(dict(CONDITIONS))
        self.fingerprint = fingerprint({"policy": POLICY, "data": data.manifest["hash"],
            "archive": data.rogue_relic_archive.fingerprint, "completion": self.base.fingerprint,
            "bands": BANDS, "band_goals": BAND_GOALS, "thresholds": THRESHOLDS})

    def evaluate(self, runs):
        if type(runs) is not tuple or any(type(run) is not RunEndingVariant for run in runs):
            raise invalid()
        # Reuse the exact mode/opening/enrollment/success/ending/time validator,
        # including rejection of bools, defeats labeled successful, and EASY.
        self.base.evaluate(tuple(run.completion for run in runs))
        qualified = set()
        for run in runs:
            if (type(run.band) is not str or run.band not in BANDS
                    or any(type(getattr(run, field)) is not int or not 0 <= getattr(run, field) < 2**31
                           for field in ("hope_left", "hope_max", "characters", "gold"))
                    or run.hope_left > run.hope_max):
                raise invalid()
            completed = run.completion
            if not completed.success or not self.base.gates.allows(completed.mode, completed.grade, completed.started_at):
                continue
            qualified.update(key for key, band in BAND_GOALS.items() if band == run.band)
            qualified.update(key for key, (field, threshold, _) in THRESHOLDS.items()
                             if getattr(run, field) >= threshold)
        return MappingProxyType({key: UnlockProgress(int(key in qualified), 1) for key in self.conditions})
