"""MissionPlayerDataGroup and MissionCalcState for frozen CN Android 2.7.71."""

from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.mission_rules import target
from terralocal.server.persistence import models as m

CATEGORIES = ("DAILY", "WEEKLY", "ACTIVITY", "MAIN", "SUB", "GUIDE", "OPENSERVER", "RETRO",
              "SPECIAL_OPERATOR", "SPECIAL_OPERATOR_WEEKLY")


def snapshot(ctx, *, at: int) -> dict:
    groups = {name: {} for name in CATEGORIES}
    valid_periods = {"permanent", ctx.clock.period("daily", at=at), ctx.clock.period("weekly", at=at)}
    rows = [row for row in ctx.rows(m.MissionProgress) if row.period in valid_periods]
    if rows:
        definitions = ctx.data.table("mission_table")["missions"]
        for row in rows:
            if row.mission_id not in definitions:
                raise DomainError("UNKNOWN_SAVED_MISSION", "存档中的任务不在当前 GameData 中", 503)
            definition = definitions[row.mission_id]
            category = definition["type"]
            if category not in groups:
                raise DomainError("MISSION_CATEGORY_UNSUPPORTED", "此任务类别尚未完成适配", 501)
            goal = target(definition)
            if row.progress < 0:
                raise DomainError("INVALID_MISSION_PROGRESS", "存档中的任务进度无效", 503)
            # Frozen MissionModel displays MAIN only in CONFIRMED=2. Whether
            # it is claimable is checked separately against value >= target
            # by MissionViewModel.CheckIfAbleToFinish, not holding state 1/2.
            state = 3 if row.claimed else 2
            groups[category][row.mission_id] = {
                "state": state, "progress": [{"target": goal, "value": min(row.progress, goal), "compare": ">="}]}
    # MAIN groups without separate rewards finish when their member missions
    # have been claimed. GUIDE group rewards require an independent claim and
    # must never be advertised as claimed from individual mission progress.
    visible_groups = {}
    if rows:
        saved = {row.mission_id: row for row in rows if row.period == "permanent"}
        for group_id, group in ctx.data.table("mission_table").get("missionGroups", {}).items():
            members = group.get("missionIds") or []
            if not any(ident in saved for ident in members):
                continue
            if group.get("type") in {"MAIN", "RETRO"} and not group.get("rewards"):
                visible_groups[group_id] = int(all(ident in saved and saved[ident].claimed for ident in members))
            elif group.get("type") == "GUIDE":
                visible_groups[group_id] = 0  # No independent group-reward claim has been implemented.
    return {"missions": groups, "missionGroups": visible_groups}
