"""First-theme cumulative command EXP and explicit per-level gains.

Frozen M33775's default branch subtracts each next-level row's exp cost,
starting at level2. Stored total EXP is not an individual row threshold.
No combat rewards, HP healing, relic effects or persistence are inferred here.
"""

from dataclasses import dataclass

from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.repository import fingerprint

FIELDS = frozenset({"exp", "populationUp", "squadCapacityUp", "battleCharLimitUp", "maxHpUp"})


@dataclass(frozen=True)
class LevelStep:
    level: int
    exp_cost: int
    hope_max: int
    squad_capacity: int
    battle_char_limit: int
    max_hp: int


@dataclass(frozen=True)
class LevelPosition:
    level: int
    total_exp: int
    in_level_exp: int
    next_level_cost: int | None


@dataclass(frozen=True)
class LevelGains:
    from_level: int
    to_level: int
    hope_max: int
    squad_capacity: int
    battle_char_limit: int
    max_hp: int


class FirstThemeLevelCurve:
    def __init__(self, levels):
        # A local parsing budget, not a claim that every theme caps at100.
        if (type(levels) is not dict or not 1 <= len(levels) <= 100
                or set(levels) != {str(i) for i in range(1, len(levels) + 1)}):
            raise ValueError("首主题指挥等级表必须连续从1开始")
        steps = []
        for level in range(1, len(levels) + 1):
            row = levels[str(level)]
            if (type(row) is not dict or set(row) != FIELDS
                    or any(type(v) is not int or not 0 <= v <= 2**31 - 1 for v in row.values())
                    or (level == 1 and any(row.values())) or (level > 1 and row["exp"] == 0)):
                raise ValueError("首主题指挥等级成本或增量不完整；不能猜默认值")
            steps.append(LevelStep(level, row["exp"], row["populationUp"], row["squadCapacityUp"],
                                   row["battleCharLimitUp"], row["maxHpUp"]))
        for name in ("exp_cost", "hope_max", "squad_capacity", "battle_char_limit", "max_hp"):
            if sum(getattr(step, name) for step in steps) > 2**31 - 1:
                raise ValueError("首主题指挥等级累计成本或增量溢出")
        self.steps, self.fingerprint = tuple(steps), fingerprint(levels)

    def at(self, total_exp: int) -> LevelPosition:
        if type(total_exp) is not int or not 0 <= total_exp <= 2**31 - 1:
            raise DomainError("ROGUE_EXP_INVALID", "探索累计指挥经验超出接纳范围")
        remaining = total_exp
        for step in self.steps[1:]:
            if remaining < step.exp_cost:
                return LevelPosition(step.level - 1, total_exp, remaining, step.exp_cost)
            remaining -= step.exp_cost
        # M33775 stops when no next row exists. It does not establish a cap on
        # stored total EXP or a max-level overflow reward, so retain surplus.
        return LevelPosition(len(self.steps), total_exp, remaining, None)

    def gains(self, before_exp: int, after_exp: int) -> LevelGains:
        before, after = self.at(before_exp), self.at(after_exp)
        if after_exp < before_exp:
            raise DomainError("ROGUE_EXP_REWIND", "升级结算不能减少既有指挥经验")
        crossed = self.steps[before.level:after.level]
        return LevelGains(before.level, after.level, *(
            sum(getattr(step, key) for step in crossed)
            for key in ("hope_max", "squad_capacity", "battle_char_limit", "max_hp")))
