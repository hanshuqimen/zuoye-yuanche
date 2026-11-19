"""Persistent account-scoped state for the local SDK compatibility adapter."""

from sqlalchemy import and_, or_, select

from terralocal.server.domain.clock import ServerClock
from terralocal.server.persistence import models as m

AGREEMENT_VERSION = 1


def consent_state(session, account_id: int) -> tuple[bool, bool]:
    latest = session.get(m.AgreementConsent, (account_id, AGREEMENT_VERSION)) is not None
    any_version = session.scalar(select(m.AgreementConsent.version).where(
        m.AgreementConsent.account_id == account_id).limit(1)) is not None
    return any_version, latest


def accept_notice(session, account_id: int) -> None:
    if session.get(m.AgreementConsent, (account_id, AGREEMENT_VERSION)) is None:
        now = ServerClock(session.get(m.ServerClockState, 1)).now()
        session.add(m.AgreementConsent(account_id=account_id, version=AGREEMENT_VERSION, accepted_at=now))
        session.add(m.AuditLog(actor="local-client", account_id=account_id, action="local-notice-accept",
                               detail={"version": AGREEMENT_VERSION}, created_at=now))


def unconfirmed_orders(session, account_id: int) -> list[str]:
    return list(session.scalars(select(m.LocalOrder.order_id).outerjoin(m.LocalCashOrder, and_(
        m.LocalOrder.account_id == m.LocalCashOrder.account_id,
        m.LocalOrder.order_id == m.LocalCashOrder.order_id)).outerjoin(m.LocalCashClaim, and_(
        m.LocalOrder.account_id == m.LocalCashClaim.account_id,
        m.LocalOrder.order_id == m.LocalCashClaim.order_id)).outerjoin(m.LocalPackOrder, and_(
        m.LocalOrder.account_id == m.LocalPackOrder.account_id,
        m.LocalOrder.order_id == m.LocalPackOrder.order_id)).outerjoin(m.LocalPackClaim, and_(
        m.LocalOrder.account_id == m.LocalPackClaim.account_id,
        m.LocalOrder.order_id == m.LocalPackClaim.order_id)).where(
        m.LocalOrder.account_id == account_id,
        or_(and_(m.LocalOrder.state == "READY", m.LocalCashOrder.order_id.is_(None),
                 m.LocalPackOrder.order_id.is_(None)), and_(
            m.LocalOrder.state.in_(("READY", "CONFIRMED")), m.LocalCashOrder.approved_at.is_not(None),
            m.LocalCashClaim.order_id.is_(None)), and_(
            m.LocalOrder.state.in_(("READY", "CONFIRMED")), m.LocalPackOrder.approved_at.is_not(None),
            m.LocalPackClaim.order_id.is_(None)))).order_by(
            m.LocalOrder.created_at, m.LocalOrder.order_id)))
