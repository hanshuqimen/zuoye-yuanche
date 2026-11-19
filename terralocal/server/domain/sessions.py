"""Session identity for commands whose client sequence restarts on login."""

from __future__ import annotations

import hashlib

from sqlalchemy import select

from terralocal.server.domain import accounts
from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.persistence import models as m


def authenticate_session(session, token: str, uid: str | None = None, *,
                         kind: str = "game") -> tuple[m.Account, m.LocalSession]:
    account = accounts.authenticate(session, token, uid)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    row = session.scalar(select(m.LocalSession).where(
        m.LocalSession.token_hash == token_hash, m.LocalSession.account_id == account.id))
    if row is None or row.kind != kind:
        raise DomainError("INVALID_SESSION", "本地登录已过期，请重新登录", 401)
    return account, row


def receipt_key(row: m.LocalSession, operation: str, key: str) -> str:
    # Include the token fingerprint as well: a later session cleanup may reuse a SQLite row ID.
    suffix = fingerprint({"session": row.token_hash, "operation": operation, "key": key})
    return f"session:{row.id}:{suffix}"


def account_receipt_key(operation: str, key: str) -> str:
    suffix = fingerprint({"operation": operation, "key": key})
    return f"local-account:{suffix}"


def battle_binding(row: m.LocalSession) -> str:
    """Private server identity; never expose the session token or its hash."""
    return fingerprint({"policy": "native-battle-session-v1", "session": row.id, "identity": row.token_hash})
