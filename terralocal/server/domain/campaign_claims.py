"""Claim owned annihilation breakthroughs from persisted eligible progress.

Qualification must come from a separate battle transaction. This service does
not infer kills, finish a battle, refresh the week or pay weekly orundum.
"""

from terralocal.server.domain import campaign
from terralocal.server.domain.errors import DomainError
from terralocal.server.persistence import models as m


def claim_breaks(ctx, stage_id: str, indices: list[int]) -> dict:
    if not campaign.available(ctx.data):
        raise DomainError("CAMPAIGN_DATA_UNAVAILABLE", "当前配置没有剿灭数据", 503)
    state = campaign.snapshot(ctx)  # Includes the immutable account/data binding.
    definition = ctx.data.campaigns.stage(stage_id)
    progress = ctx.session.get(m.CampaignStageProgress, (ctx.account_id, stage_id))
    if progress is None:
        raise DomainError("CAMPAIGN_UNDISCOVERED", "此账号尚未开放该剿灭实例")
    if not indices or len(indices) != len(set(indices)):
        raise DomainError("INVALID_CAMPAIGN_REWARD_INDICES", "突破奖励序号不能为空或重复")
    selected = []
    for index in indices:
        if type(index) is not int or not 0 <= index < len(definition.break_ladders):
            raise DomainError("INVALID_CAMPAIGN_REWARD_INDEX", "突破奖励序号无效")
        if ctx.session.get(m.CampaignBreakClaim, (ctx.account_id, stage_id, index)) is not None:
            raise DomainError("CAMPAIGN_REWARD_ALREADY_CLAIMED", "此突破奖励已领取", 409)
        ladder = definition.break_ladders[index]
        if progress.max_kills < ladder.kills:
            raise DomainError("CAMPAIGN_REWARD_NOT_ELIGIBLE", "尚未达到此突破奖励的歼灭数")
        selected.append((index, ladder))
    fee_add = sum(ladder.fee_add for _, ladder in selected)
    if state["campaignTotalFee"] + fee_add > 2**31 - 1:
        raise DomainError("CAMPAIGN_FEE_OVERFLOW", "剿灭已解锁周上限超出客户端整数范围")
    items = []
    for index, ladder in selected:
        rewards = [{"id": r.item_id, "count": r.count, "type": r.item_type} for r in ladder.rewards]
        granted = ctx.rewards([reward for reward in rewards if reward["count"] > 0])
        items.extend({"id": reward["id"], "type": reward["type"], "count": reward["count"],
                      "charGet": reward.get("charGet")} for reward in granted)
        ctx.session.add(m.CampaignBreakClaim(account_id=ctx.account_id, stage_id=stage_id,
            ladder_index=index, fee_add=ladder.fee_add, rewards=rewards, claimed_at=ctx.now))
    ctx.session.flush()
    # Validate the persisted ledger as projected by both full sync and deltas.
    campaign.snapshot(ctx)
    return {"feeAdd": fee_add, "items": items}
