"""Durable weekly campaign income, with a monotonic period watermark.

The frozen client's default calendar uses Monday 04:00 at UTC+8. Moving the
local clock backwards never reopens an archived earning allowance. That rewind
policy is local; no claim of official administrative-clock behavior is made.
"""

from datetime import date

from terralocal.server.domain.errors import DomainError
from terralocal.server.persistence import models as m

POLICY_VERSION = "cn-campaign-week-monday-04-v1"


def _invalid():
    return DomainError("CAMPAIGN_WEEK_INCOMPATIBLE", "剿灭周账本缺失或与收入不一致，请保留存档", 503)


def active_week(ctx, account):
    rows = sorted(ctx.read_rows(m.CampaignWeek), key=lambda row: row.period)
    if not rows:
        raise _invalid()
    for index, row in enumerate(rows):
        try:
            parsed = date.fromisoformat(row.period)
        except (ValueError, TypeError):
            raise _invalid() from None
        if (parsed.isoformat() != row.period or parsed.weekday() != 0
                or row.period < "1969-12-29" or row.policy_version != POLICY_VERSION
                or type(row.earned_fee) is not int or not 0 <= row.earned_fee <= 2**31 - 1
                or (row.closed_at is None) != (index == len(rows) - 1)
                or row.closed_at is not None and (type(row.closed_at) is not int
                    or not 0 <= row.closed_at <= 253_402_271_999)):
            raise _invalid()
    active = rows[-1]
    if active.earned_fee != account.current_fee:
        raise _invalid()
    return active


def initialize(ctx):
    from terralocal.server.domain.campaign import _account

    account = _account(ctx)
    if not ctx.read_rows(m.CampaignWeek):
        if account.current_fee != 0:
            raise _invalid()
        ctx.session.add(m.CampaignWeek(account_id=ctx.account_id, period=ctx.clock.period("weekly"),
            policy_version=POLICY_VERSION, earned_fee=0))
        ctx.session.flush()
    active_week(ctx, account)


def advance(ctx) -> bool:
    from terralocal.server.domain.campaign import _account, available

    if not available(ctx.data):
        return False
    account = _account(ctx)
    active = active_week(ctx, account)
    period = ctx.clock.period("weekly")
    if period <= active.period:
        return False
    ctx.session.get(m.CampaignWeek, (ctx.account_id, active.period)).closed_at = ctx.now
    ctx.session.add(m.CampaignWeek(account_id=ctx.account_id, period=period,
        policy_version=POLICY_VERSION, earned_fee=0))
    account.current_fee = 0
    ctx.session.flush()
    active_week(ctx, account)
    return True
