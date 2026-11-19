"""Countable mission parameters established from the frozen CN GameData.

Template parameter layouts differ. The category, target and battle conditions
are resolved explicitly instead of treating the first/last argument as a
universal stage ID/count.
"""

from terralocal.server.domain.errors import DomainError

BATTLE_TEMPLATES = {"CompleteStage", "CompleteMainStage", "CompleteStageAnyType"}
PERMANENT_TEMPLATES = BATTLE_TEMPLATES | {"UpgradeChar", "CompleteAnyStage"}


def _integer(raw, minimum=1, maximum=2_000_000_000) -> int:
    if (not isinstance(raw, str) or not raw.isascii() or not raw.isdigit()
            or not minimum <= int(raw) <= maximum):
        raise DomainError("MISSION_DEFINITION_INVALID", "任务计数参数无效", 503)
    return int(raw)


def upgrade_char_rule(definition) -> dict:
    """Frozen UpgradeChar: operation count, or distinct phase/level-qualified operators."""
    params = definition.get("param") or []
    if definition.get("template") != "UpgradeChar":
        raise DomainError("MISSION_TEMPLATE_UNSUPPORTED", "此任务不是干员养成规则", 501)
    if len(params) == 2 and params[0] == "0":
        rule = {"mode": 0, "target": _integer(params[1])}
    elif len(params) == 4 and params[0] == "1":
        rule = {"mode": 1, "target": _integer(params[1]),
                "phase": _integer(params[2], 0, 2), "level": _integer(params[3], 1, 90)}
    else:
        raise DomainError("MISSION_TEMPLATE_UNSUPPORTED", "此干员养成任务参数尚未完成适配", 501)
    if definition.get("templateType", str(rule["mode"])) != str(rule["mode"]):
        raise DomainError("MISSION_DEFINITION_INVALID", "任务参数与模板子类型不一致", 503)
    return rule


def target(definition) -> int:
    params = definition.get("param") or []
    template = definition["template"]
    if template == "UpgradeChar":
        return upgrade_char_rule(definition)["target"]
    if template == "CompleteAnyStage":
        any_stage_rule(definition)
        return 1
    if template == "CompleteStage" and len(params) in {2, 3}:
        raw = params[-1]
    elif template == "CompleteMainStage" and len(params) == 3 and params[0] == "1" and params[2] == "1":
        raw = "1"  # Frozen MAIN missions are one successful clear of params[1].
    elif template == "CompleteStageAnyType" and len(params) == 3 and params[0] == "0":
        raw = params[1]
    else:
        raise DomainError("MISSION_TEMPLATE_UNSUPPORTED", "此任务的计数参数尚未完成适配", 501)
    return _integer(raw)


def any_stage_rule(definition, data=None) -> dict:
    """One of an explicit caret-separated set must reach PASS(2)/COMPLETE(3).

    The final parameter is PlayerStageState, not an occurrence count. Persisted
    domain stars 1/2 both project to PASS; only three stars project to COMPLETE.
    """
    params = definition.get("param")
    if (definition.get("template") != "CompleteAnyStage" or not isinstance(params, list)
            or len(params) != 3 or params[0] != "0" or params[2] not in {"2", "3"}
            or definition.get("templateType", "0") != "0" or not isinstance(params[1], str)):
        raise DomainError("MISSION_TEMPLATE_UNSUPPORTED", "此候选关卡任务参数尚未完成适配", 501)
    stages = params[1].split("^")
    if not 1 <= len(stages) <= 64 or any(not stage for stage in stages) or len(set(stages)) != len(stages):
        raise DomainError("MISSION_DEFINITION_INVALID", "候选关卡列表无效", 503)
    if data is not None and any(stage not in data.stages for stage in stages):
        raise DomainError("MISSION_DEFINITION_INVALID", "候选关卡不在当前数据版本中", 503)
    return {"stages": tuple(stages), "minimum_stars": 1 if params[2] == "2" else 3}


def matches_battle(definition, stage, *, stars: int, practice: bool) -> bool:
    params = definition.get("param") or []
    template = definition["template"]
    if template == "CompleteStage" and len(params) == 3:
        if params[0] == "0":
            return not practice and stars > 0 and params[1] == stage["stageId"]
        if params[0] == "2" and params[1] in {"1", "2", "3"}:
            return not practice and stars >= int(params[1])
    elif template == "CompleteStage" and len(params) == 2 and params[0] == "3":
        return practice and stars > 0
    elif template == "CompleteMainStage" and len(params) == 3 and params[0] == params[2] == "1":
        return not practice and stars > 0 and params[1] == stage["stageId"]
    elif template == "CompleteStageAnyType" and len(params) == 3 and params[0] == "0" and params[2] in {"2", "3"}:
        return not practice and stars >= int(params[2])
    return False
