from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select

from terralocal.server.domain import accounts, battle, operators
from terralocal.server.domain.errors import DomainError
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply, diff
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


def command(runtime, token, key, name, body, callback):
    return runtime.mutate(token, None, key, name, body, callback)


def test_atomic_rollback_after_partial_grant(runtime, token):
    before = runtime.sync(token)
    def action(ctx):
        ctx.change_item("material", 10)
        ctx.change_item("4001", -10000)
        return {}
    with pytest.raises(DomainError):
        command(runtime, token, "rollback", "grant", {}, action)
    assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        assert session.scalar(select(m.Receipt)) is None


def test_duplicate_receipt_and_conflict(runtime, token):
    def action(ctx):
        ctx.change_item("material", 3)
        return {"granted": 3}
    first = command(runtime, token, "grant-1", "grant", {"count": 3}, action)
    assert command(runtime, token, "grant-1", "grant", {"count": 3}, action) == first
    assert runtime.sync(token)["user"]["inventory"]["material"] == 3
    with pytest.raises(DomainError, match="幂等键"):
        command(runtime, token, "grant-1", "grant", {"count": 4}, action)


def test_account_isolation(runtime, token):
    with runtime.database.transaction() as session:
        second = accounts.create_account(session, runtime.data, "Doctor B")
        secret = accounts.login(session, runtime.settings, name="Doctor B")["secret"]
        other_op = session.scalar(select(m.Operator.id).where(m.Operator.account_id == second.id))
    with pytest.raises(DomainError):
        command(runtime, token, "foreign-op", "upgrade", {}, lambda ctx: operators.upgrade(
            ctx, other_op, [{"id": "2001", "count": 1}]))
    assert runtime.sync(secret)["user"]["status"]["gold"] == 1000
    with pytest.raises(DomainError):
        runtime.sync(secret, runtime.sync(token)["user"]["status"]["uid"])


def test_sanity_recovery_and_rewind(runtime, token):
    command(runtime, token, "start", "start", {}, lambda ctx: battle.start(ctx, "test_1", "0"))
    assert runtime.sync(token)["user"]["status"]["ap"] == 4
    with runtime.database.transaction() as session:
        session.get(m.ServerClockState, 1).fixed_at += 721
    state = runtime.sync(token)["user"]["status"]
    assert state["ap"] == 6 and state["lastApAddTime"] == 1_800_000_720
    with runtime.database.transaction() as session:
        session.get(m.ServerClockState, 1).fixed_at -= 720
    assert runtime.sync(token)["user"]["status"]["ap"] == 6


def test_concurrent_duplicate_start(runtime, token):
    def start(_):
        return command(runtime, token, "same", "start", {}, lambda ctx: battle.start(ctx, "test_1", "0"))
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(start, range(8)))
    assert len({r["battleId"] for r in results}) == 1
    assert runtime.sync(token)["user"]["status"]["ap"] == 4


def test_delta_nested_delete_and_list_replacement():
    before = {"x": {"a": 1, "b": {"c": 3}}, "list": [1, 2]}
    after = {"x": {"b": {"d": 4}}, "list": [3]}
    assert apply(before, diff(before, after)) == after


def test_backup_restore_and_integrity_guard(runtime, token):
    service = BackupService(runtime)
    saved = service.create()
    command(runtime, token, "grant", "grant", {}, lambda ctx: (ctx.change_item("material", 9) or {}))
    service.restore(saved["name"])
    assert "material" not in runtime.sync(token)["user"]["inventory"]
    path = service.directory / saved["name"]
    with path.open("ab") as stream:
        stream.write(b"corrupted")
    with pytest.raises(ValueError, match="哈希"):
        service.restore(saved["name"])
    assert runtime.database.integrity() == "ok"


def test_golden_playthrough_domain_restart(runtime, token):
    with runtime.database.transaction() as session:
        session.add(m.Mail(account_id=1, title="Test supplies", body="Synthetic", created_at=1_800_000_000,
                           rewards=[{"id": "2001", "count": 1}]))
        op_id = session.scalar(select(m.Operator.id))
    from terralocal.server.domain import mail
    command(runtime, token, "mail", "mail", {}, lambda ctx: mail.claim(ctx, [2]))
    command(runtime, token, "upgrade", "upgrade", {}, lambda ctx: operators.upgrade(
        ctx, op_id, [{"id": "2001", "count": 1}]))
    command(runtime, token, "squad", "squad", {}, lambda ctx: operators.formation(
        ctx, "0", [{"charInstId": op_id, "skillIndex": 0}], "Golden"))
    started = command(runtime, token, "start", "start", {}, lambda ctx: battle.start(ctx, "test_1", "0"))
    before = runtime.sync(token)["user"]
    finished = command(runtime, token, "finish", "finish", {}, lambda ctx: battle.finish(
        ctx, started["battleId"], 3, drop_rules=runtime.drop_rules))
    after = runtime.sync(token)["user"]
    assert apply(before, finished["playerDataDelta"]) == after
    assert after["inventory"]["material"] == 1
    assert after["status"]["freeDiamond"] == 1
    command(runtime, token, "finish-again", "finish", {}, lambda ctx: battle.finish(
        ctx, started["battleId"], 3, drop_rules=runtime.drop_rules))
    assert runtime.sync(token)["user"]["status"]["freeDiamond"] == 1
    runtime.database.close()
    restarted = Runtime(runtime.settings)
    try:
        assert restarted.sync(token)["user"] == after
    finally:
        restarted.database.close()
