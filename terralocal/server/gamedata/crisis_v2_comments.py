"""Imported first-season comment conditions, evaluated without any DB writes.

Rules are a documented local interpretation of the imported definitions and
client counters; not recovered official backend code. Missing required inputs
produce unavailable IDs, never a fabricated zero or silently earned comment.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from types import MappingProxyType

from terralocal.server.gamedata.crisis_v2 import CLIENT_ELF_SHA256
from terralocal.server.gamedata.crisis_v2 import CONTRACT as MAP_CONTRACT
from terralocal.server.gamedata.crisis_v2_challenges import natural
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.protocol.crisis_v2_counters import ATTRIBUTES, EVENTS

CONTRACT = "cn-2.7.71-crisis-v2-comments-v1"
PROFESSIONS = frozenset({"SNIPER", "CASTER", "WARRIOR", "SUPPORT", "PIONEER", "SPECIAL", "MEDIC", "TANK"})


@dataclass(frozen=True)
class Condition:
    kind: str
    keys: tuple[str, ...]
    threshold: Decimal
    order: int


@dataclass(frozen=True)
class CommentResult:
    earned: tuple[str, ...]
    unavailable: tuple[str, ...]


class CrisisV2CommentRules:
    def __init__(self, detail, map_rules):
        if fingerprint({"contract": MAP_CONTRACT, "client_elf": CLIENT_ELF_SHA256,
                "data": map_rules.data_hash, "map_id": map_rules.map_id, "detail": detail}) != map_rules.fingerprint:
            raise ValueError("危机合约评语来源与绑定地图不一致")
        source = detail.get("commentDataMap")
        if type(source) is not dict:
            raise ValueError("危机合约评语定义缺失")
        conditions = {}
        for ident, row in source.items():
            if (type(ident) is not str or not ident or type(row) is not dict or row.get("id") != ident
                    or type(row.get("sortId")) is not int or row["sortId"] < 0):
                raise ValueError("危机合约评语标识或顺序无效")
            params, kind = row.get("paramList"), row.get("condition")
            if (type(kind) is not str or type(params) is not list
                    or any(type(v) is not str for v in params) or not params):
                raise ValueError("危机合约评语参数无效")
            try:
                threshold = Decimal(params[-1])
                if not threshold.is_finite() or not 0 <= threshold <= 2**31-1:
                    raise ValueError()
            except (InvalidOperation, ValueError) as exc:
                raise ValueError("危机合约评语阈值无效") from exc
            keys = ()
            if kind == "PassWithDimensionScoreMore" and len(params) == 2:
                keys = tuple(params[0].split(";"))
                axes = tuple(natural(v) for v in keys)
                if len(set(axes)) != len(axes) or any(v >= 6 for v in axes):
                    raise ValueError("危机合约评语维度无效")
                natural(params[-1])
            elif kind in {"PassWithDeployLess", "PassWithDeployMore"} and len(params) == 1:
                natural(params[-1])
            elif kind == "PassWithSpecProf" and len(params) == 2 and params[0] in PROFESSIONS:
                keys = (params[0],)
                if not 1 <= natural(params[-1]) <= 12:
                    raise ValueError("危机合约职业编队条件无效")
            elif kind == "PassWithEventLess" and len(params) == 2 and params[0] in EVENTS:
                keys = (params[0],)
                natural(params[-1])
            elif kind in {"PassWithAttrExistMore", "PassWithAttrAllLess"} and len(params) == 2:
                keys = (params[0],)
                if params[0] not in ATTRIBUTES:
                    raise ValueError("危机合约评语属性尚未适配")
            elif kind == "KillWithSpecSlot" and len(params) == 4:
                # Only the actually imported single prerequisite is admitted.
                # Do not generalize the unexplored second parameter to all maps.
                if (params[1] != "1" or params[0] not in map_rules.nodes
                        or map_rules.nodes[params[0]].kind != "NORMAL" or not params[2]):
                    raise ValueError("危机合约指定指标击杀条件尚未适配")
                keys = (params[0], params[2])
                natural(params[-1])
            else:
                raise ValueError("危机合约评语条件尚未适配")
            conditions[ident] = Condition(kind, keys, threshold, row["sortId"])
        self.conditions = MappingProxyType(conditions)
        self.map_fingerprint = map_rules.fingerprint
        self.fingerprint = fingerprint({"contract": CONTRACT, "map_rules": self.map_fingerprint})

    def evaluate(self, evaluation, counters, professions, *, cleared):
        if type(cleared) is not bool or evaluation.rules_fingerprint != self.map_fingerprint:
            raise ValueError("危机合约评语需要绑定地图的明确结果")
        if (type(professions) is not tuple or not 1 <= len(professions) <= 12
                or any(v not in PROFESSIONS for v in professions)):
            raise ValueError("危机合约评语需要有效的开战编队职业")
        if not cleared:
            return CommentResult((), ())
        earned, unavailable = [], []
        for ident, rule in sorted(self.conditions.items(), key=lambda p: (p[1].order, p[0])):
            result = self._satisfied(rule, evaluation, counters, professions)
            if result is None:
                unavailable.append(ident)
            elif result:
                earned.append(ident)
        return CommentResult(tuple(earned), tuple(unavailable))

    @staticmethod
    def _satisfied(rule, evaluation, counters, professions):
        kind, keys, threshold = rule.kind, rule.keys, rule.threshold
        if kind == "PassWithDimensionScoreMore":
            return sum(evaluation.dimension_scores[int(k)] for k in keys) >= threshold
        if kind == "PassWithSpecProf":
            return professions.count(keys[0]) >= threshold
        if kind in {"PassWithDeployLess", "PassWithDeployMore"}:
            if counters.characters is None:
                return None
            count = counters.characters.spawns  # Native writer already applies ignoreCharStats.
            return count <= threshold if kind.endswith("Less") else count >= threshold
        if kind == "KillWithSpecSlot":
            if keys[0] not in evaluation.rune_slots:
                return False
            if counters.enemies is None:
                return None
            # Count only this target's HP_ZERO, including invalid-kill rows;
            # encounters/exits and validKillCnt are not interchangeable deaths.
            return sum(r.value for r in counters.enemies if r.enemy == keys[1] and r.kind == "HP_ZERO") >= threshold
        if not counters.has_end_marker:
            return None  # An absent game-over marker is not a known zero event.
        if kind == "PassWithEventLess":
            if keys[0] == "COST":
                value = next(r.value for r in counters.extra if r.kind == "SIMPLE" and not r.entity and r.name == "COST")
                return value <= threshold
            return sum(r.value for r in counters.extra if r.kind in {"SIMPLE", "DETAILED"} and r.name == keys[0]) <= threshold
        rows = [r for r in counters.extra if r.kind == "ATTRIBUTE" and r.name == keys[0] and r.value > 0]
        scale = 1000 if keys[0] == "HP_RATIO" else 1
        if kind == "PassWithAttrExistMore":
            return any(Decimal(r.sample)/scale >= threshold for r in rows)
        # Non-vacuous: no escaped enemy cannot earn the all-low-health comment.
        return bool(rows) and all(Decimal(r.sample)/scale <= threshold for r in rows)
