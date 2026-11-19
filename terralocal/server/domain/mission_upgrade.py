"""Transactional UpgradeChar progress; locked groups and unassigned daily pools stay inactive."""

from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.mission_rules import upgrade_char_rule
from terralocal.server.persistence import models as m


def progress(ctx, event: str) -> None:
    from terralocal.server.domain.missions import _definition, _group, _prerequisites

    table = ctx.data.table("mission_table")
    owned = None
    for mission_id, definition in table["missions"].items():
        if definition.get("template") != "UpgradeChar":
            continue
        kind = {"DAILY": "daily", "WEEKLY": "weekly"}.get(definition.get("type"), "permanent")
        period = ctx.clock.period(kind, at=ctx.now)
        row = ctx.session.get(m.MissionProgress, (ctx.account_id, mission_id, period))
        if kind == "permanent":
            checked = _definition(table, mission_id)
            group = _group(table, checked)
            try:
                _prerequisites(ctx, table, checked, group)
            except DomainError as error:
                if error.code in {"MISSION_LOCKED", "MISSION_GROUP_UNSUPPORTED"}:
                    # Separate predecessor rewards cannot be inferred from
                    # individual claims. Do not manufacture an unlocked group.
                    continue
                raise
            if row is None:
                row = m.MissionProgress(account_id=ctx.account_id, mission_id=mission_id,
                                        period=period, progress=0, claimed=False)
                ctx.session.add(row)
        if row is None or row.claimed:
            continue
        if row.progress < 0:
            raise DomainError("INVALID_MISSION_PROGRESS", "存档中的任务进度无效", 503)
        rule = upgrade_char_rule(definition)
        if rule["mode"] == 0:
            # A promotion is not an EXP-material reinforcement operation.
            if event == "OperatorLeveled":
                row.progress += 1
        else:
            if owned is None:
                owned = ctx.rows(m.Operator)
            qualified = sum(op.evolve_phase > rule["phase"] or (
                op.evolve_phase == rule["phase"] and op.level >= rule["level"]) for op in owned)
            row.progress = max(row.progress, qualified)
