"""Account-scoped annihilation state, separate from ordinary stage progress.

No battle completion, mission qualification or reward payout is
inferred here. Initialized values are zero; only separately persisted claims
contribute to the unlocked cap. Reads never invent kills, sweeps or claims.
"""

import sqlite3
from contextlib import closing

from terralocal.server.domain.errors import DomainError
from terralocal.server.persistence import models as m
from terralocal.server.protocol.campaign_state import CampaignOpen, CampaignStage, CampaignState

POLICY_VERSION = "campaign-state-v1"


def available(data) -> bool:
    return data is not None and "campaign_table" in data.manifest["tables"]


def initial_fee(data) -> int:
    value = data.constants.get("initCampaignTotalFee")
    if type(value) is not int or not 0 <= value <= 2**31 - 1:
        raise ValueError("剿灭需要匹配 GameData 的 initCampaignTotalFee")
    return value


def preflight(data, path, *, require_existing_binding: bool = False) -> None:
    """Check an admitted save before SQLite migrations or initialization."""
    enabled = available(data)
    if enabled:
        # Force optional catalog validation before opening the writable save.
        _ = data.campaigns
        expected_fee = initial_fee(data)
    if not path.exists():
        return
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        exists = "campaign_accounts" in tables
        rows = connection.execute("SELECT gamedata_hash, policy_version, initial_fee FROM campaign_accounts").fetchall() if exists else []
        if require_existing_binding and "accounts" in tables:
            missing = (connection.execute("SELECT 1 FROM accounts a LEFT JOIN campaign_accounts c "
                "ON a.id=c.account_id WHERE c.account_id IS NULL LIMIT 1").fetchone() if exists
                else connection.execute("SELECT 1 FROM accounts LIMIT 1").fetchone())
            if missing:
                raise ValueError("独立剿灭测试配置需要新存档，不能自动迁移已有账号的版本绑定")
        if exists:
            # A nonzero legacy total has no trustworthy week attribution. Do
            # not silently attach it to startup time, then erase it on reset.
            missing_week = (connection.execute("SELECT 1 FROM campaign_accounts c WHERE c.current_fee != 0 "
                "AND NOT EXISTS (SELECT 1 FROM campaign_weeks w WHERE w.account_id=c.account_id) LIMIT 1").fetchone()
                if "campaign_weeks" in tables else
                connection.execute("SELECT 1 FROM campaign_accounts WHERE current_fee != 0 LIMIT 1").fetchone())
            if missing_week:
                raise ValueError("已有剿灭收入缺少所属周记录；请保留原存档，不能猜测或清空其周收入")
    for digest, policy, fee in rows:
        if (not enabled or digest != data.manifest["hash"] or policy != POLICY_VERSION or fee != expected_fee):
            raise ValueError("已有剿灭存档绑定了其他 GameData 或规则；请保留原配置并使用独立测试存档")


def _account(ctx):
    row = ctx.session.get(m.CampaignAccount, ctx.account_id)
    if (row is None or row.gamedata_hash != ctx.data.manifest["hash"]
            or row.policy_version != POLICY_VERSION or row.initial_fee != initial_fee(ctx.data)):
        raise DomainError("CAMPAIGN_STATE_INCOMPATIBLE", "剿灭存档缺少初始化或版本绑定不匹配", 503)
    return row


def initialize(ctx) -> None:
    """Discover introduced stages without marking any ordinary stage cleared.

    Discovery uses the first table opening as a local calendar policy. Keep
    earlier discoveries on clock rewind. No official snapshot has yet proved
    the exact server-side discovery policy; native gameplay remains unverified.
    """
    if not available(ctx.data):
        return
    catalog = ctx.data.campaigns
    if ctx.session.get(m.CampaignAccount, ctx.account_id) is None:
        ctx.session.add(m.CampaignAccount(account_id=ctx.account_id, gamedata_hash=ctx.data.manifest["hash"],
            policy_version=POLICY_VERSION, initial_fee=initial_fee(ctx.data), current_fee=0, initialized_at=ctx.now))
        ctx.session.flush()
    _account(ctx)
    from terralocal.server.domain.campaign_weeks import initialize as initialize_week

    initialize_week(ctx)
    known = {r.stage_id for r in ctx.rows(m.CampaignStageProgress)}
    for stage_id, timestamp in catalog.introduced.items():
        if timestamp <= ctx.now and stage_id not in known:
            ctx.session.add(m.CampaignStageProgress(account_id=ctx.account_id, stage_id=stage_id,
                                                    max_kills=0, sweep_max_kills=None))
    missions = {r.mission_id for r in ctx.rows(m.CampaignMission)}
    for mission_id in catalog.mission_fees.keys() - missions:
        ctx.session.add(m.CampaignMission(account_id=ctx.account_id, mission_id=mission_id, state=0))
    ctx.session.flush()


def snapshot(ctx, *, at: int | None = None) -> dict:
    """Project seven native fields from persisted records, without writes."""
    account = _account(ctx)
    from terralocal.server.domain.campaign_weeks import active_week

    active_week(ctx, account)
    catalog = ctx.data.campaigns
    opening = catalog.opening(ctx.now if at is None else at)
    instances = {}
    sweeps = {}
    for row in ctx.read_rows(m.CampaignStageProgress):
        if row.stage_id not in catalog.definitions:
            raise DomainError("CAMPAIGN_STATE_INCOMPATIBLE", "剿灭纪录引用未知关卡", 503)
        instances[row.stage_id] = CampaignStage(maxKills=row.max_kills,
            rewardStatus=[0] * len(catalog.stage(row.stage_id).break_ladders))
        if row.sweep_max_kills is not None:
            sweeps[row.stage_id] = row.sweep_max_kills
    total = account.initial_fee
    for claim in ctx.read_rows(m.CampaignBreakClaim):
        definition = catalog.definitions.get(claim.stage_id)
        if (claim.stage_id not in instances or definition is None
                or not 0 <= claim.ladder_index < len(definition.break_ladders)
                or claim.fee_add != definition.break_ladders[claim.ladder_index].fee_add):
            raise DomainError("CAMPAIGN_STATE_INCOMPATIBLE", "剿灭突破领取纪录与版本不匹配", 503)
        ladder = definition.break_ladders[claim.ladder_index]
        expected_rewards = [{"id": r.item_id, "count": r.count, "type": r.item_type} for r in ladder.rewards]
        if instances[claim.stage_id].maxKills < ladder.kills or claim.rewards != expected_rewards:
            raise DomainError("CAMPAIGN_STATE_INCOMPATIBLE", "剿灭突破领取纪录缺少对应击杀或奖励快照", 503)
        instances[claim.stage_id].rewardStatus[claim.ladder_index] = 1
        total += claim.fee_add
    missions = {}
    for row in ctx.read_rows(m.CampaignMission):
        if row.mission_id not in catalog.mission_fees or (row.state == 2 and row.fee_add != catalog.mission_fees[row.mission_id]):
            raise DomainError("CAMPAIGN_STATE_INCOMPATIBLE", "剿灭委托领取纪录与版本不匹配", 503)
        missions[row.mission_id] = row.state
        if row.state == 2:
            total += row.fee_add
    if total > 2**31 - 1:
        raise DomainError("CAMPAIGN_FEE_OVERFLOW", "剿灭已解锁周上限超出客户端整数范围", 503)
    return CampaignState(campaignCurrentFee=account.current_fee, campaignTotalFee=total,
        activeGroupId=opening.active_group,
        open=CampaignOpen(permanent=list(opening.permanent), training=list(opening.training), rotate=opening.rotate,
            rotateGroup=opening.rotate_group, trainingGroup=opening.training_group,
            trainingAllOpenGroup=opening.training_all_group),
        instances=instances, missions=missions, sweepMaxKills=sweeps).model_dump(by_alias=True)
