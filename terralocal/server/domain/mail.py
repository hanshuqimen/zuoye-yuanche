from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.persistence import models as m


def list_mail(ctx: Context) -> list[dict]:
    return [{"id": row.id, "title": row.title, "body": row.body, "sender": row.sender,
             "rewards": row.rewards, "createdAt": row.created_at, "expiresAt": row.expires_at,
             "read": row.read, "claimed": row.claimed} for row in ctx.rows(m.Mail)
            if row.expires_at is None or row.expires_at > ctx.now]


def claim(ctx: Context, mail_ids: list[int]) -> dict:
    rewards, claimed = [], []
    for mail_id in dict.fromkeys(mail_ids):
        row = ctx.session.get(m.Mail, mail_id)
        if row is None or row.account_id != ctx.account_id:
            raise DomainError("UNKNOWN_MAIL", "邮件不存在", 404)
        if row.expires_at is not None and row.expires_at <= ctx.now:
            raise DomainError("MAIL_EXPIRED", "邮件已过期")
        if row.claimed:
            continue
        ctx.rewards(row.rewards)
        row.read, row.claimed = True, True
        rewards.extend(row.rewards)
        claimed.append(row.id)
    return {"rewards": rewards, "claimed": claimed}
