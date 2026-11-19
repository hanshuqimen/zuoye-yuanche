"""Credit rewards and costs remain distinct from procurement vouchers in sync."""

import pytest

from terralocal.server.domain.accounts import create_account
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.protocol.sync import SyncDataAssembler
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


@pytest.mark.parametrize("legacy_balance", [None, 91])
def test_credit_reward_uses_credit_balance_and_keeps_procurement_independent(runtime, legacy_balance):
    with runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 1)
        ctx.rewards([{"id": "SOCIAL_PT", "count": 73}, {"id": "4006", "count": 37}])
        if legacy_balance is not None:
            session.add(m.Currency(account_id=1, item_id="4006", balance=legacy_balance))
        snapshot = SyncDataAssembler(ctx).assemble()
        assert ctx.balance("SOCIAL_PT") == snapshot["status"]["socialPoint"] == 73
        assert ctx.balance("4006") == snapshot["inventory"]["4006"] == 37
        assert "SOCIAL_PT" not in snapshot["inventory"]
        if legacy_balance is not None:
            assert session.get(m.Currency, (1, "4006")).balance == legacy_balance


def test_credit_grant_and_cost_commit_once_with_matching_delta(runtime, token):
    before = runtime.sync(token)["user"]

    def grant(ctx):
        return {"items": ctx.rewards([{"id": "SOCIAL_PT", "count": 73}, {"id": "4006", "count": 37}])}

    granted = runtime.mutate(token, None, "credit-grant", "synthetic-credit-grant", {}, grant)
    assert runtime.mutate(token, None, "credit-grant", "synthetic-credit-grant", {}, grant) == granted
    after_grant = runtime.sync(token)["user"]
    assert apply(before, granted["playerDataDelta"]) == after_grant
    assert after_grant["status"]["socialPoint"] == 73

    def cost(ctx):
        ctx.consume([{"id": "SOCIAL_PT", "count": 21}])
        return {}

    spent = runtime.mutate(token, None, "credit-cost", "synthetic-credit-cost", {}, cost)
    assert runtime.mutate(token, None, "credit-cost", "synthetic-credit-cost", {}, cost) == spent
    after_cost = runtime.sync(token)["user"]
    assert apply(after_grant, spent["playerDataDelta"]) == after_cost
    assert after_cost["status"]["socialPoint"] == 52
    assert after_cost["inventory"]["4006"] == 37


def test_insufficient_credit_rolls_back_reward_and_entire_snapshot(runtime, token):
    with runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 1)
        ctx.change_item("SOCIAL_PT", 73)
        ctx.change_item("4006", 37)
    before = runtime.sync(token)

    def failed(ctx):
        ctx.change_item("4006", 4)
        ctx.consume([{"id": "SOCIAL_PT", "count": 100}])
        return {}

    with pytest.raises(DomainError, match="不足"):
        runtime.mutate(token, None, "credit-failed", "synthetic-credit-cost", {}, failed)
    assert runtime.sync(token) == before


def test_credit_and_procurement_snapshots_do_not_leak_between_accounts(runtime):
    with runtime.database.transaction() as session:
        other = create_account(session, runtime.data, "CreditOther")
        ours, foreign = Context(session, runtime.data, 1), Context(session, runtime.data, other.id)
        ours.rewards([{"id": "SOCIAL_PT", "count": 42}, {"id": "4006", "count": 37}])
        foreign.rewards([{"id": "SOCIAL_PT", "count": 101}, {"id": "4006", "count": 91}])
        one, two = SyncDataAssembler(ours).assemble(), SyncDataAssembler(foreign).assemble()
        assert (one["status"]["socialPoint"], one["inventory"]["4006"]) == (42, 37)
        assert (two["status"]["socialPoint"], two["inventory"]["4006"]) == (101, 91)


def test_credit_and_procurement_survive_backup_restore_and_restart(runtime, token):
    with runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 1)
        ctx.rewards([{"id": "SOCIAL_PT", "count": 73}, {"id": "4006", "count": 37}])
    expected = runtime.sync(token)
    service = BackupService(runtime)
    saved = service.create()
    with runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 1)
        ctx.consume([{"id": "SOCIAL_PT", "count": 73}, {"id": "4006", "count": 37}])
    assert runtime.sync(token)["user"]["status"]["socialPoint"] == 0
    service.restore(saved["name"])
    assert runtime.sync(token) == expected
    runtime.database.close()
    restarted = Runtime(runtime.settings)
    try:
        assert restarted.sync(token) == expected
        assert restarted.database.integrity() == "ok"
    finally:
        restarted.database.close()
