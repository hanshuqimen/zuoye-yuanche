"""Merchant qualification from the owned bank chain, never a saved UI claim."""

from dataclasses import dataclass

from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.persistence import models as m


def invalid():
    return DomainError("ROGUE_BANK_ITEM_INCOMPATIBLE", "银行收藏品资格缺少已核结算来源；请保留原存档", 503)


@dataclass(frozen=True)
class Qualification:
    items: frozenset[str]
    digest: str


def qualification(ctx, run):
    from terralocal.server.domain.rogue_banks import verify_account
    from terralocal.server.domain.rogue_ending import history_in_session

    try:
        if (run.account_id != ctx.account_id or run.gamedata_hash != ctx.data.manifest["hash"]
                or run.topic_id != "rogue_1" or run.mode != "NORMAL"
                or type(run.grade) is not int or run.grade != 0
                or type(run.created_at) is not int or not 0 <= run.created_at < 2**63
                or ctx.session.get(m.RogueTopicRun, run.id) is not run):
            raise invalid()
        ctx.data.rogue_topics.topic(run.topic_id, at=run.created_at)
        rules = ctx.data.rogue_bank_items
        verified = verify_account(ctx)
        grants = []
        if verified is not None:
            # Bank replay validates hashes/ownership and the award event, while
            # ending replay independently validates its causal score history.
            history_in_session(ctx)
            wallet = ctx.session.get(m.RogueBankWallet, ctx.account_id)
            grants = [row for row in wallet.awards
                      if row["run"] != run.id and row["at"] <= run.created_at]
        rewards = {key for row in grants for key in row["rewards"]}
        items = frozenset(key for key, reward in rules.bindings.items() if reward in rewards)
        return Qualification(items, fingerprint({"rules": rules.fingerprint, "account": ctx.account_id,
            "run": run.id, "data": run.gamedata_hash, "started": run.created_at, "grants": grants}))
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise invalid() from exc
