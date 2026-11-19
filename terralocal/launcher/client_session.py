"""Finite SDK credentials issued only by the trusted local launcher.

No network route calls this module. Binding an account is a desktop owner
action, just like the launcher's existing access to the local database.
"""
from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass, field

from sqlalchemy import select

from terralocal.server.persistence import models as m


class ClientConnectionError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class LocalCredential:
    account_id: int
    account_uid: str = field(repr=False)
    code: str = field(repr=False)
    expires_at: int

    def callback(self) -> dict:
        return {"code": self.code, "isSuc": True, "type": 1}


def prepare_credential(runtime, account_id: int, account_uid: str,
                       previous: LocalCredential | None = None, *, now: int | None = None,
                       cancel=None) -> LocalCredential:
    at = int(time.time()) if now is None else now
    # A short configured TTL still has an overlap window instead of issuing a
    # new credential on every health poll. Normal TTL rotates five minutes early.
    margin = min(300, max(1, runtime.settings.session_ttl // 4))
    with runtime.maintenance, runtime.database.transaction() as session:
        if cancel is not None and cancel.is_set():
            raise ClientConnectionError("CLIENT_CANCELLED", "连接已停止")
        account = session.get(m.Account, account_id)
        if account is None or account.uid != account_uid:
            raise ClientConnectionError("BOUND_ACCOUNT_MISSING", "绑定的存档已不存在，请重新选择账号")
        if previous is not None and (previous.account_id, previous.account_uid) == (account.id, account.uid):
            row = session.scalar(select(m.LocalSession).where(
                m.LocalSession.token_hash == hashlib.sha256(previous.code.encode()).hexdigest()))
            if (row is not None and row.account_id == account.id and row.kind == "sdk"
                    and row.expires_at > at + margin):
                return LocalCredential(account.id, account.uid, previous.code, row.expires_at)
        code = secrets.token_urlsafe(32)
        expires = at + runtime.settings.session_ttl
        session.add(m.LocalSession(account_id=account.id, kind="sdk", expires_at=expires,
                                   token_hash=hashlib.sha256(code.encode()).hexdigest()))
        # Preparing the login file is not a player login. Keep last-online time,
        # gameplay revisions, receipts and reward state untouched.
        return LocalCredential(account.id, account.uid, code, expires)
