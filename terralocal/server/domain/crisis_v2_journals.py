"""Explicit opt-in archive of a bounded, owned local Crisis V2 clear journal."""

import hashlib
import json

from sqlalchemy import func, select

from terralocal.server.domain import crisis_v2_battles, crisis_v2_clears
from terralocal.server.domain.errors import DomainError
from terralocal.server.persistence.models import Receipt

PREFIX = "crisis-v2-journal:"
VERSION = "local-crisis-v2-journal-v1"
MAX_WIRE = 1_000_000
MAX_PER_ACCOUNT = 20


def _validate(settlement, state, key, battle_id, digest, body):
    if (state != "FINISHED" or type(settlement) is not dict
            or not crisis_v2_clears.is_clear_version(settlement.get("version"))
            or key != PREFIX + battle_id or type(body) is not dict or set(body) != {"version", "battleLog"}
            or digest != settlement.get("journal_hash") or body["version"] != VERSION):
        raise ValueError("危机合约战斗原始日志缺少同一场通关回执")
    encoded = body["battleLog"]
    if (type(encoded) is not str or not 1 <= len(encoded) <= MAX_WIRE
            or hashlib.sha256(encoded.encode("ascii")).hexdigest() != digest):
        raise ValueError("危机合约战斗原始日志内容或摘要不匹配")


def archive(ctx, battle, journal):
    if journal is None or len(journal.encoded) > MAX_WIRE:
        return
    count = ctx.session.scalar(select(func.count()).select_from(Receipt).where(
        Receipt.account_id == ctx.account_id, Receipt.key.startswith(PREFIX)))
    if count >= MAX_PER_ACCOUNT:
        return
    key = PREFIX + battle.id
    body = {"version": VERSION, "battleLog": journal.encoded}
    _validate(battle.settlement, battle.state, key, battle.id, journal.sha256, body)
    ctx.session.add(Receipt(account_id=ctx.account_id, key=key, request_hash=journal.sha256,
                            result=body, created_at=ctx.now))


def load(ctx, battle_id):
    stored = ctx.session.get(Receipt, (ctx.account_id, PREFIX + battle_id))
    if stored is None:
        raise DomainError("CRISIS_V2_JOURNAL_NOT_FOUND", "此战斗没有已归档的原始日志", 404)
    pending = crisis_v2_battles.context(ctx, battle_id)
    battle = pending.battle
    try:
        _validate(battle.settlement, battle.state, stored.key, battle.id, stored.request_hash, stored.result)
    except (ValueError, TypeError, KeyError) as exc:
        raise DomainError("CRISIS_V2_JOURNAL_INCOMPATIBLE", "本地原始日志校验失败", 503) from exc
    return {"battleId": battle_id, "version": VERSION, "battleLog": stored.result["battleLog"],
            "playableReplay": False}


def preflight(connection):
    for key, digest, raw, ident, state, saved in connection.execute(
            """SELECT r.key,r.request_hash,r.result,b.id,b.state,b.settlement FROM receipts r
               LEFT JOIN crisis_v2_battles c ON c.battle_id=substr(r.key,?) AND c.account_id=r.account_id
               LEFT JOIN battle_sessions b ON b.id=c.battle_id AND b.account_id=r.account_id
               WHERE substr(r.key,1,?)=?""", (len(PREFIX) + 1, len(PREFIX), PREFIX)):
        if ident is None:
            raise ValueError("危机合约原始日志没有所属战斗")
        _validate(json.loads(saved) if saved is not None else None, state, key, ident, digest, json.loads(raw))
