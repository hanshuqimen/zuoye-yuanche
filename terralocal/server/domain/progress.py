"""Current normal mainline stage, derived without inventing save progress."""

from terralocal.server.domain.battle import unlocked
from terralocal.server.domain.context import Context
from terralocal.server.persistence import models as m

POLICY_VERSION = "cn-android-2.7.71-normal-mainline-progress-v1"


def main_stage_progress(ctx: Context, progress: dict[str, m.StageProgress]) -> str | None:
    for stage_id in ctx.data.mainline_progress_order:
        saved = progress.get(stage_id)
        if (saved is None or saved.stars == 0) and unlocked(ctx, stage_id, progress=progress):
            return stage_id
    return None
