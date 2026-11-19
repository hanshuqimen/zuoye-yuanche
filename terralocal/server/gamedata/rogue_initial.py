"""Admitted first-theme base-run rules, bound to the actual topic definitions.

Group recipes translate the three explicit profession lists in the CN table's
descriptions; there is no machine-readable recipe in recruitGrps. Conditional
random/challenge groups and mode-specific relics are not silently substituted.
"""

from types import MappingProxyType

from terralocal.server.domain.errors import DomainError

RECIPES = {
    "recruit_group_1": ("PIONEER", "SNIPER", "SPECIAL"),
    "recruit_group_2": ("TANK", "CASTER", "SNIPER"),
    "recruit_group_3": ("WARRIOR", "SUPPORT", "MEDIC"),
}


class FirstThemeInitialRules:
    topic_id = "rogue_1"

    def __init__(self, data):
        self.topic = data.rogue_topics.topic(self.topic_id)
        if self.topic.modules:
            raise ValueError("首主题基础开局不能含未实现模块")
        table = data.table("roguelike_topic_table")
        detail = table["details"][self.topic_id]
        self.config = self.topic.starting_state("NORMAL", 0)
        self.configs = MappingProxyType({mode: self.topic.starting_state(mode, 0)
                                        for mode in ("EASY", "NORMAL")})
        # Both base difficulties share this initialization recipe, but their
        # budgets remain independent (the frozen table grants EASY more gold).
        if any(c.bands != self.config.bands or c.recruit_groups != self.config.recruit_groups
               for c in self.configs.values()):
            raise ValueError("基础难度分队或招募配方不同，不能套用同一初始化流程")
        bands = [key for key in self.config.bands if detail["items"][key].get("type") == "BAND"
                 and detail["items"][key].get("unlockCondDesc") is None]
        if len(bands) != 1:
            raise ValueError("首主题基础开局缺少唯一无条件分队，不能猜测初始解锁")
        self.band = bands[0]
        # Retain the actual per-battle effect. Selection does not grant four
        # permanent lives or manufacture a battle settlement.
        buffs = detail["relics"][self.band].get("buffs")
        if (not isinstance(buffs, list) or len(buffs) != 1 or buffs[0].get("key") != "level_life_point_add"
                or not isinstance(buffs[0].get("blackboard"), list)):
            raise ValueError("初始分队战斗效果未匹配，不能忽略未知效果")
        values = buffs[0]["blackboard"]
        if len(values) != 1 or values[0].get("key") != "value":
            raise ValueError("初始分队战斗效果参数不完整")
        value = values[0].get("value")
        if type(value) not in (int, float) or not 0 <= value <= 2**31 - 1 or int(value) != value:
            raise ValueError("初始分队临时生命参数非法")
        self.battle_temporary_hp = int(value)
        cooldown = table["constant"].get("ordiModeReOpenCoolDown")
        if type(cooldown) is not int or not 0 <= cooldown <= 86400:
            raise ValueError("集成战略重开冷却非法")
        self.cooldown = cooldown
        levels = detail.get("detailConst", {}).get("playerLevelTable")
        if (not isinstance(levels, dict) or not levels or any(
                not isinstance(key, str) or not key.isdecimal() or str(int(key)) != key for key in levels)):
            raise ValueError("集成战略指挥等级表非法")
        self.max_level = len(levels)
        if set(levels) != {str(i) for i in range(1, self.max_level + 1)}:
            raise ValueError("集成战略指挥等级必须连续从1开始")
        groups = {}
        for group in self.config.recruit_groups:
            definition = detail["recruitGrps"][group]
            if definition.get("unlockDesc") is not None:
                continue  # Conditional groups require separately persisted qualification.
            if group not in RECIPES:
                raise ValueError("未接纳的初始招募组合，不能用默认组合替代")
            tickets = []
            for profession in RECIPES[group]:
                candidates = [key for key, row in detail["recruitTickets"].items()
                    if row.get("profession") == profession and row.get("professionList") == [profession]
                    and row.get("rarity") == "ALL" and row.get("extraEliteNum") == 0
                    and row.get("extraFreeRarity") == []
                    and detail["items"][key].get("type") == "RECRUIT_TICKET"]
                if len(candidates) != 1:
                    raise ValueError("初始普通招募券不唯一或缺失，不能混入高级/猩红券")
                tickets.append(candidates[0])
            groups[group] = tuple(tickets)
        if set(groups) != set(RECIPES):
            raise ValueError("首主题三个基础招募组合不完整")
        self.groups = MappingProxyType(groups)

    def require_base(self, mode: str, grade: int, predefined: str | None, activity: str | None):
        self.topic.starting_state(mode, grade, predefined)
        if mode not in self.configs or grade != 0 or predefined is not None or activity:
            raise DomainError("ROGUE_MODE_UNSUPPORTED", "此难度、预设或活动开局尚未接通，未创建探索", 501)
        return self.configs[mode]
