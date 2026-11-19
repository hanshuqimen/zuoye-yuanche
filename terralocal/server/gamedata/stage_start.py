"""Required owned operators for the frozen stageStartConds schema."""

from terralocal.server.domain.errors import DomainError


def requirements(data, stage_id: str) -> dict | None:
    rule = data.table("stage_table").get("stageStartConds", {}).get(stage_id)
    if rule is None:
        return None
    if (not isinstance(rule, dict) or set(rule) != {"requireChars", "excludeAssists", "isNotPass"}
            or type(rule["isNotPass"]) is not bool or not isinstance(rule["requireChars"], list)
            or not rule["requireChars"] or len(rule["requireChars"]) > 12
            or not isinstance(rule["excludeAssists"], list)):
        raise DomainError("GAMEDATA_INVALID", "关卡干员前置定义无效", 503)
    phases = {"PHASE_0": 0, "PHASE_1": 1, "PHASE_2": 2}
    required = {}
    for row in rule["requireChars"]:
        if (not isinstance(row, dict) or set(row) != {"charId", "evolvePhase"}
                or not isinstance(row.get("charId"), str) or row["charId"] not in data.characters
                or not isinstance(row.get("evolvePhase"), str) or row["evolvePhase"] not in phases
                or row["charId"] in required):
            raise DomainError("GAMEDATA_INVALID", "关卡干员或精英阶段引用无效", 503)
        required[row["charId"]] = phases[row["evolvePhase"]]
        if required[row["charId"]] >= len(data.characters[row["charId"]].get("phases") or []):
            raise DomainError("GAMEDATA_INVALID", "关卡要求的精英阶段超出干员定义", 503)
    if any(not isinstance(cid, str) or cid not in data.characters for cid in rule["excludeAssists"]):
        raise DomainError("GAMEDATA_INVALID", "关卡助战限制引用无效", 503)
    return {"first_pass_only": rule["isNotPass"], "operators": required,
            "excluded_assists": tuple(rule["excludeAssists"])}
