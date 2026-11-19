"""First-theme map references, separate from unknown server generation weights.

Catalog membership alone grants no unlocks or rewards. The separate regional
placement adapter restricts ordinary stage pools; generation still requires
explicit weights, and hidden floors/endings require their own prerequisites.
There is no all-stages/default-map fallback.
"""

from dataclasses import dataclass
from types import MappingProxyType

from terralocal.server.gamedata.roguelike import identifier, integer, invalid

NODE_TYPES = frozenset({"BATTLE_NORMAL", "BATTLE_ELITE", "BATTLE_BOSS", "SHOP", "REST", "INCIDENT",
                        "TREASURE", "ENTERTAINMENT", "UNKNOWN"})
BATTLE_TYPES = frozenset({"BATTLE_NORMAL", "BATTLE_ELITE", "BATTLE_BOSS"})


@dataclass(frozen=True)
class MapStage:
    id: str
    level_id: str
    kind: str
    difficulty: str
    linked_stage: str | None


class FirstThemeMapCatalog:
    topic_id = "rogue_1"

    def __init__(self, data):
        topic = data.rogue_topics.topic(self.topic_id)
        detail = data.table("roguelike_topic_table")["details"][self.topic_id]
        if topic.modules or set(detail.get("nodeTypeData", {})) != NODE_TYPES:
            raise invalid("首主题节点类型或模块未匹配")
        stages = {}
        for key, row in detail["stages"].items():
            boss, elite = row.get("isBoss"), row.get("isElite")
            if type(boss) is not int or type(elite) is not int or boss not in (0, 1) or elite not in (0, 1):
                raise invalid("地图战斗分类标志必须为明确0/1")
            if boss and elite:
                raise invalid("首主题战斗同时标记Boss和紧急，不能猜分类优先级")
            kind = "BATTLE_BOSS" if boss else "BATTLE_ELITE" if elite else "BATTLE_NORMAL"
            difficulty = row.get("difficulty")
            if difficulty != ("FOUR_STAR" if elite else "NORMAL"):
                raise invalid("首主题紧急标记与战斗难度不一致")
            stages[key] = MapStage(key, identifier(row["levelId"], "levelId"), kind, difficulty,
                                   row.get("linkedStageId") or None)
        # Only explicit linkedStageId establishes a variant relationship. Never
        # replace '_n_' with '_e_' and presume an unlisted variant exists.
        variants = {}
        for stage in stages.values():
            if stage.linked_stage is None:
                continue
            normal = stages[stage.linked_stage]
            if (stage.kind != "BATTLE_ELITE" or normal.kind != "BATTLE_NORMAL"
                    or normal.linked_stage is not None or normal.id in variants):
                raise invalid("首主题紧急关与普通关的明确引用不唯一或不匹配")
            variants[normal.id] = stage.id
        zones = {}
        for key, row in detail["zones"].items():
            if type(row.get("isHiddenZone")) is not bool:
                raise invalid("区域隐藏标记必须为布尔值")
            zones[key] = row["isHiddenZone"]
        portals = detail.get("gameConst", {}).get("portalZones")
        if (not isinstance(portals, list) or any(not isinstance(p, str) or p not in zones for p in portals)
                or len(set(portals)) != len(portals)):
            raise invalid("首主题额外区域列表不完整或引用非法")
        self.portal_zones = frozenset(portals)
        self.stages, self.zones, self.emergency_variants = (
            MappingProxyType(stages), MappingProxyType(zones), MappingProxyType(variants))
        from terralocal.server.gamedata.rogue_placements import load

        self.placements = load(data, self.stages, self.zones, self.portal_zones)

    def require_node(self, kind: str, stage_id: str | None) -> None:
        if not isinstance(kind, str) or kind not in NODE_TYPES or kind == "UNKNOWN":
            raise invalid("未接纳的实际节点类型；迷雾可见性不能代替节点内容")
        if kind in BATTLE_TYPES:
            if not isinstance(stage_id, str):
                raise invalid("战斗节点必须明确指定关卡")
            stage = self.stages.get(stage_id)
            if stage is None or stage.kind != kind:
                raise invalid("节点战斗引用或分类不匹配")
        elif stage_id is not None:
            raise invalid("非战斗节点不能携带战斗关卡")

    def require_zone(self, zone_id: str) -> None:
        identifier(zone_id, "地图区域")
        if zone_id not in self.zones:
            raise invalid("地图区域不在当前主题")
        if zone_id in self.portal_zones:
            raise invalid("额外区域不能套用尚未接纳的普通层图规则")

    def require_placement(self, kind: str, stage_id: str | None, zone_id: str) -> None:
        self.require_zone(zone_id)
        self.require_node(kind, stage_id)
        if stage_id is not None:
            self.placements.require(stage_id, zone_id)

    def require_seed(self, seed: int) -> None:
        integer(seed, "地图种子", signed=True)
        if seed < 0:
            raise invalid("地图种子不能为负")
