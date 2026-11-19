"""Owned explicit bank visits, shared payments and a replayed account wallet.

Plans are internal reviewed inputs, not official encounter or fault sampling.
No request may supply a price, outcome, balance or withdrawal entitlement.
Legacy shops and unknown legacy bank snapshots are never rewritten on startup.
"""

import json
import sqlite3
from contextlib import closing
from dataclasses import asdict
from types import SimpleNamespace

from sqlalchemy import select

from terralocal.server.domain import rogue_bank_awards as awards
from terralocal.server.domain import rogue_bank_ledger as ledger
from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.repository import canonical, fingerprint
from terralocal.server.persistence import models as m

POLICY = "rogue1-explicit-bank-wallet-v1"
ZERO = {"show": False, "current": 0, "record": 0, "totalPut": 0, "reward": {}}


def invalid():
    return DomainError("ROGUE_BANK_INCOMPATIBLE", "银行保存、访问或账号余额链不一致；请保留原存档", 503)


def saved_plan(terms, outcomes, has_boss):
    if (type(outcomes) is not tuple or len(outcomes) > ledger.MAX_ACTIONS
            or any(type(v) is not bool for v in outcomes) or type(has_boss) is not bool):
        raise invalid()
    return {"terms": asdict(terms) | {"withdrawal_costs": list(terms.withdrawal_costs)},
            "outcomes": list(outcomes), "hasBoss": has_boss}


def terms_for(data, run, q, plan):
    if (type(plan) is not dict or set(plan) != {"terms", "outcomes", "hasBoss"}
            or type(plan["terms"]) is not dict or type(plan["outcomes"]) is not list):
        raise invalid()
    t = plan["terms"]
    expected = {"policy", "rules_hash", "quote_hash", "bank_open", "allow_deposit", "allow_withdraw",
                "withdrawal_costs", "evidence"}
    if set(t) != expected or type(t["withdrawal_costs"]) is not list:
        raise invalid()
    terms = ledger.compile_terms(data, q, mode=run.mode, grade=run.grade, bank_open=t["bank_open"],
        allow_deposit=t["allow_deposit"], allow_withdraw=t["allow_withdraw"],
        withdrawal_costs=tuple(t["withdrawal_costs"]), evidence=t["evidence"])
    if run.topic_id != "rogue_1" or canonical(saved_plan(terms, tuple(plan["outcomes"]), plan["hasBoss"])) != canonical(plan):
        raise invalid()
    return terms


def plan_hash(run, draft, shop, plan):
    return fingerprint({"policy": POLICY, "data": run.gamedata_hash, "run": run.id, "account": run.account_id,
        "seed": run.seed, "map": draft.plan_hash, "visit": shop.id, "quote": shop.rule_hash,
        "zone": shop.zone_index, "x": shop.node_x, "y": shop.node_y, "plan": plan})


def arguments(data, run, shop, bank, terms):
    return (data.rogue_bank, _quote(data, shop), terms, bank.before_bank, shop.before["gold"],
            shop.entered_at, shop.first_ticket, ledger.Scope(shop.account_id, shop.run_id, shop.id))


def _quote(data, shop):
    from terralocal.server.domain.rogue_shops import quote

    return quote(data, shop)


def financial(data, run, draft, shop, bank):
    """Independent per-visit verification, usable before a writable DB opens."""
    try:
        q = _quote(data, shop)
        terms = terms_for(data, run, q, bank.plan)
        if (bank.policy_version != POLICY or bank.visit_id != shop.id
                or bank.account_id != shop.account_id or bank.run_id != shop.run_id
                or shop.account_id != run.account_id or shop.run_id != run.id
                or bank.plan_hash != plan_hash(run, draft, shop, bank.plan)
                or type(bank.prepared_at) is not int or not shop.prepared_at <= bank.prepared_at < 2**63
                or run.ended_at is not None and bank.prepared_at > run.ended_at):
            raise invalid()
        if shop.state == "PREPARED":
            if bank.ordinal is not None or bank.before_bank != {} or bank.faulted_before is not None or bank.journal != {}:
                raise invalid()
            return terms, None
        if (type(bank.ordinal) is not int or not 0 <= bank.ordinal < 2**31
                or type(bank.faulted_before) is not bool or shop.entered_at < bank.prepared_at):
            raise invalid()
        journal = ledger.load(bank.journal)
        state = ledger.replay(*arguments(data, run, shop, bank, terms), journal, faulted_before=bank.faulted_before)
        if ([asdict(p) for p in state.purchases] != shop.purchases or state.ended_at != shop.ended_at):
            raise invalid()
        outcomes = [a.fault_after for a in journal.actions if a.kind == "PUT"]
        if outcomes != bank.plan["outcomes"][:len(outcomes)] or len(outcomes) > len(bank.plan["outcomes"]):
            raise invalid()
        return terms, state
    except (DomainError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise invalid() from exc


def in_session(session, account_id):
    bank_rows = session.scalars(select(m.RogueBankVisit).where(m.RogueBankVisit.account_id == account_id)).all()
    return [(b, session.get(m.RogueShopVisit, b.visit_id), session.get(m.RogueTopicRun, b.run_id),
             session.get(m.RogueMapDraft, b.run_id)) for b in bank_rows]


def fold(data, entries, *, award_log=None, settlements=None):
    """A contiguous account visit chain; per-run faults reset only on a new run."""
    ordered, faults, traces = [], {}, []
    grants = awards.load(data.rogue_bank, [] if award_log is None else award_log)
    settlements = {} if settlements is None else settlements
    consumed = 0
    for b, shop, run, draft in entries:
        terms, state = financial(data, run, draft, shop, b)
        if state is not None:
            ordered.append((b, shop, run, terms, state))
    ordered.sort(key=lambda v: v[0].ordinal)
    balance = ZERO | {"reward": {}}
    pending = False
    for number, (b, shop, run, terms, state) in enumerate(ordered):
        if b.ordinal != number or pending:
            raise invalid()
        expected = balance | {"show": balance["show"] or terms.bank_open}
        if canonical(b.before_bank) != canonical(expected) or b.faulted_before != faults.get(run.id, False):
            raise invalid()
        balance = state.bank_snapshot(b.before_bank)
        faults[run.id] = state.faulty
        traces.append([b.visit_id, b.plan_hash, b.before_bank, b.faulted_before, b.journal])
        pending = shop.state == "ACTIVE"
        if consumed < len(grants) and grants[consumed]["visits"] == number + 1:
            grant = grants[consumed]
            if (pending or shop.ended_at is None or grant["run"] != run.id
                    or type(grant["at"]) is not int or grant["at"] < shop.ended_at):
                raise invalid()
            head = fingerprint({"policy": POLICY, "chain": traces})
            balance = awards.apply(data.rogue_bank, balance, grant, run, settlements.get(run.id),
                                   visits=number + 1, head=head)
            traces.append(["AWARD", grant])
            consumed += 1
    if consumed != len(grants):
        raise invalid()
    return balance, len(ordered), fingerprint({"policy": POLICY, "chain": traces}), faults


def settlement_rows(ctx, wallet):
    log = awards.load(ctx.data.rogue_bank, getattr(wallet, "awards", []))
    return {row["run"]: ctx.session.get(m.RogueGameSettlement, row["run"]) for row in log}


def verify_account(ctx):
    entries = in_session(ctx.session, ctx.account_id)
    wallet = ctx.session.get(m.RogueBankWallet, ctx.account_id)
    if wallet is None and not entries:
        return None
    outer = ctx.session.get(m.RogueTopicOuter, (ctx.account_id, "rogue_1"))
    if outer is None:
        raise invalid()
    return verify(ctx.data, ctx.account_id, wallet, entries, outer.state["bank"],
                  settlements=settlement_rows(ctx, wallet))


def verify(data, account_id, wallet, entries, outer_bank, *, settlements=None):
    balance, count, head, faults = fold(data, entries, award_log=getattr(wallet, "awards", []), settlements=settlements)
    if wallet is None:
        if count:
            raise invalid()
        return None  # Prepared plans do not convert unknown legacy balances.
    if (wallet.account_id != account_id or wallet.policy_version != POLICY
            or wallet.gamedata_hash != data.manifest["hash"] or wallet.visits != count
            or wallet.head_hash != head or canonical(wallet.state) != canonical(balance)
            or canonical(outer_bank) != canonical(balance)):
        raise invalid()
    return balance, count, head, faults


def refresh(ctx):
    wallet = ctx.session.get(m.RogueBankWallet, ctx.account_id)
    if wallet is None:
        raise invalid()
    balance, count, head, _ = fold(ctx.data, in_session(ctx.session, ctx.account_id),
                                 award_log=wallet.awards, settlements=settlement_rows(ctx, wallet))
    wallet.state, wallet.visits, wallet.head_hash = balance, count, head
    outer = ctx.session.get(m.RogueTopicOuter, (ctx.account_id, "rogue_1"))
    outer.state = outer.state | {"bank": balance}
    ctx.session.flush()


def prepare(ctx, visit_id, terms, *, outcomes, has_boss):
    """Internal explicit plans only; no client or GM balance/entitlement API."""
    from terralocal.server.domain.rogue_visits import context

    run, _, _, draft = context(ctx)
    shop = ctx.session.get(m.RogueShopVisit, visit_id)
    if shop is None or shop.account_id != ctx.account_id or shop.run_id != run.id or shop.state != "PREPARED":
        raise DomainError("ROGUE_BANK_PLAN_TARGET", "银行方案只能绑定本账号未进入的当前探索商店", 409)
    plan = saved_plan(terms, outcomes, has_boss)
    terms_for(ctx.data, run, _quote(ctx.data, shop), plan)
    old = ctx.session.get(m.RogueBankVisit, visit_id)
    if old is not None:
        financial(ctx.data, run, draft, shop, old)
        if canonical(old.plan) != canonical(plan):
            raise DomainError("ROGUE_BANK_PLAN_CONFLICT", "此商店已有不同银行方案", 409)
        return
    bank = m.RogueBankVisit(visit_id=visit_id, account_id=ctx.account_id, run_id=run.id,
        policy_version=POLICY, plan=plan, plan_hash=plan_hash(run, draft, shop, plan),
        prepared_at=max(ctx.now, shop.prepared_at), ordinal=None, before_bank={}, faulted_before=None, journal={})
    financial(ctx.data, run, draft, shop, bank)
    ctx.session.add(bank)
    ctx.session.flush()


def earned_terms(ctx, shop_quote, *, mode, grade, open_bank):
    """Compile reviewed first-theme terms from verified, settled reward keys.

    Opening and fault samples still require their own trusted sources. This
    derives only the entitlement; it never turns a high record into a key.
    """
    if type(open_bank) is not bool:
        raise invalid()
    verified = verify_account(ctx)
    if verified is None:
        outer = ctx.session.get(m.RogueTopicOuter, (ctx.account_id, "rogue_1"))
        if outer is None or canonical(outer.state["bank"]) != canonical(ZERO):
            raise invalid()
        bank = ZERO
    else:
        bank = verified[0]
    opened = bank["show"] or open_bank
    withdraw = opened and any(row.kind == "UNLOCK_WITHDRAW" and key in bank["reward"]
                             for key, row in ctx.data.rogue_bank.rewards.items())
    return ledger.compile_terms(ctx.data, shop_quote, mode=mode, grade=grade, bank_open=opened,
        allow_deposit=opened, allow_withdraw=withdraw, withdrawal_costs=(1, 2, 4, 8, 16, 32),
        evidence="Verified settled first-theme bank journal keys; PRTS first-theme capped doubling costs. "
                 "Opening/fault inputs are separate, not inferred from this entitlement.")


def prepare_earned(ctx, visit_id, *, open_bank, outcomes, has_boss):
    from terralocal.server.domain.rogue_visits import context

    run, _, _, _ = context(ctx)
    shop = ctx.session.get(m.RogueShopVisit, visit_id)
    if shop is None or shop.account_id != ctx.account_id or shop.run_id != run.id or shop.state != "PREPARED":
        raise DomainError("ROGUE_BANK_PLAN_TARGET", "银行方案只能绑定本账号未进入的当前探索商店", 409)
    terms = earned_terms(ctx, _quote(ctx.data, shop), mode=run.mode, grade=run.grade, open_bank=open_bank)
    prepare(ctx, visit_id, terms, outcomes=outcomes, has_boss=has_boss)


def enter(ctx, run, draft, shop):
    b = ctx.session.get(m.RogueBankVisit, shop.id)
    if b is None:
        return
    # Verify the committed account chain before initializing this new entry.
    other = [e for e in in_session(ctx.session, ctx.account_id) if e[0].visit_id != shop.id]
    outer = ctx.session.get(m.RogueTopicOuter, (ctx.account_id, "rogue_1"))
    wallet = ctx.session.get(m.RogueBankWallet, ctx.account_id)
    results = settlement_rows(ctx, wallet)
    verify(ctx.data, ctx.account_id, wallet, other, outer.state["bank"], settlements=results)
    if wallet is None:
        if canonical(outer.state["bank"]) != canonical(ZERO):
            raise DomainError("ROGUE_BANK_LEGACY_UNVERIFIED", "已有银行余额来源未接纳，未转换或覆盖原保存", 503)
        empty_head = fingerprint({"policy": POLICY, "chain": []})
        wallet = m.RogueBankWallet(account_id=ctx.account_id, gamedata_hash=ctx.data.manifest["hash"],
            policy_version=POLICY, state=ZERO | {"reward": {}}, visits=0, head_hash=empty_head)
        ctx.session.add(wallet)
        ctx.session.flush()
    balance, count, _, faults = fold(ctx.data, other, award_log=wallet.awards, settlements=results)
    terms = terms_for(ctx.data, run, _quote(ctx.data, shop), b.plan)
    shop.entered_at = max(shop.entered_at, b.prepared_at)
    b.ordinal, b.faulted_before = count, faults.get(run.id, False)
    b.before_bank = balance | {"show": balance["show"] or terms.bank_open}
    b.journal = ledger.dump(ledger.begin(*arguments(ctx.data, run, shop, b, terms), faulted_before=b.faulted_before))
    ctx.session.flush()
    refresh(ctx)


def settle(ctx, run, result):
    """Award once with score/closure, never on PUT or on opening the list.

    Old completed explorations are not retroactively rewritten. A supported
    award must follow this run's own closed bank visit and confirmed result.
    Unknown legacy balances remain unconverted; the public marker is opaque.
    """
    wallet = ctx.session.get(m.RogueBankWallet, ctx.account_id)
    if wallet is None:
        return
    balance, count, head, _ = verify_account(ctx)
    if not awards.pending(ctx.data.rogue_bank, balance):
        return
    entered = [(b, shop) for b, shop, owned, _ in in_session(ctx.session, ctx.account_id)
               if owned.id == run.id and b.ordinal is not None]
    if not entered:
        return  # Do not invent a new source for a pre-upgrade completed run.
    b, shop = max(entered, key=lambda pair: pair[0].ordinal)
    if (b.ordinal != count - 1 or shop.state not in ("FINISHED", "ABANDONED") or shop.ended_at is None
            or shop.ended_at > result.created_at):
        raise invalid()
    grant = awards.event(ctx.data.rogue_bank, balance, run, result, visits=count, head=head)
    if grant is not None:
        wallet.awards = wallet.awards + [grant]
        ctx.session.flush()
        refresh(ctx)


def transact(ctx, run, draft, shop, *, key, kind, index=None, forced_close=False):
    """Same transaction as run gold, owned shop effects and Runtime receipts."""
    verify_account(ctx)
    b = ctx.session.get(m.RogueBankVisit, shop.id)
    if b is None:
        raise DomainError("ROGUE_BANK_PLAN_MISSING", "当前商店没有经过准备的银行记录", 503)
    terms, before = financial(ctx.data, run, draft, shop, b)
    journal = ledger.load(b.journal)
    fault = None
    if kind == "PUT":
        used = sum(a.kind == "PUT" for a in journal.actions)
        old = next((a for a in journal.actions if a.key == key), None)
        if old:
            fault = old.fault_after
        elif before.faulty or not terms.allow_deposit:
            raise DomainError("ROGUE_BANK_PUT_UNAVAILABLE", "当前探索不能继续投资", 409)
        elif used < len(b.plan["outcomes"]):
            fault = b.plan["outcomes"][used]
        else:
            raise DomainError("ROGUE_BANK_OUTCOME_MISSING", "缺少下一笔投资结果的来源；未扣款或发奖", 503)
    if forced_close and kind != "LEAVE":
        raise invalid()
    pending = not forced_close and ctx.session.scalar(select(m.RogueRunTicket.ordinal).where(
        m.RogueRunTicket.run_id == run.id, m.RogueRunTicket.state != "DONE").limit(1)) is not None
    journal, state = ledger.decide(*arguments(ctx.data, run, shop, b, terms), journal,
        faulted_before=b.faulted_before, key=key, kind=kind, at=ctx.now, index=index,
        fault_after=fault, recruit_pending=pending)
    b.journal = ledger.dump(journal)
    shop.purchases = [asdict(p) for p in state.purchases]
    if state.ended_at is not None:
        shop.state, shop.ended_at = "FINISHED", state.ended_at
    run.gold = state.gold
    ctx.session.flush()
    refresh(ctx)
    return state


def action(ctx, kind, key):
    from terralocal.server.domain.rogue_visits import authorize, context, path_in_session

    authorize(ctx)
    run, _, zone, draft = context(ctx)
    entries = path_in_session(ctx, run, zone)[0]
    if not entries or entries[-1][2] != "shop" or entries[-1][3].state != "ACTIVE":
        raise DomainError("ROGUE_BANK_NOT_PENDING", "当前不在可处理的商店银行", 409)
    transact(ctx, run, draft, entries[-1][3], key=key, kind=kind)
    return {}


def pending(data, run, draft, shop):
    b = getattr(shop, "_bank_visit", None)
    if b is None:
        return None
    terms, state = financial(data, run, draft, shop, b)
    return {"cost": ledger.withdrawal_cost(terms, state.withdrawals), "open": terms.bank_open,
        "canPut": terms.allow_deposit and not state.faulty, "canWithdraw": terms.allow_withdraw,
        "withdraw": state.withdrawals, "withdrawLimit": 0}, b.plan["hasBoss"]


def read_visits(con, run_id):
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='rlv2_bank_visits'").fetchone():
        return {}
    result = {}
    for raw in con.execute('SELECT * FROM rlv2_bank_visits WHERE run_id=?', (run_id,)):
        value = dict(raw)
        for key in ("plan", "before_bank", "journal"):
            value[key] = json.loads(value[key])
        if value["faulted_before"] is not None:
            if value["faulted_before"] not in (0, 1):
                raise invalid()
            value["faulted_before"] = bool(value["faulted_before"])
        result[value["visit_id"]] = SimpleNamespace(**value)
    return result


def preflight(data, path):
    if not path.exists():
        return
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as con:
        con.row_factory = sqlite3.Row
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        names = {"rlv2_bank_visits", "rlv2_bank_wallets"}
        if not names <= tables:
            from terralocal.server.persistence.migrations import REVISION, ROGUE_BANK_AWARDS_REVISION

            v = con.execute('SELECT version_num FROM alembic_version').fetchone() if 'alembic_version' in tables else None
            if tables & names or v and v[0] in (ROGUE_BANK_AWARDS_REVISION, REVISION):
                raise ValueError(invalid().message)
            return
        try:
            from terralocal.server.persistence.migrations import REVISION, ROGUE_BANK_AWARDS_REVISION

            version = con.execute('SELECT version_num FROM alembic_version').fetchone()
            columns = {row[1] for row in con.execute('PRAGMA table_info(rlv2_bank_wallets)')}
            if version and version[0] in (ROGUE_BANK_AWARDS_REVISION, REVISION) and "awards" not in columns:
                raise invalid()
            by_account = {}
            for raw in con.execute('SELECT DISTINCT run_id FROM rlv2_bank_visits'):
                run_id = raw[0]
                run = con.execute('SELECT * FROM rlv2_runs WHERE id=?', (run_id,)).fetchone()
                draft = con.execute('SELECT * FROM rlv2_map_drafts WHERE run_id=?', (run_id,)).fetchone()
                if run is None or draft is None:
                    raise invalid()
                run, draft = SimpleNamespace(**dict(run)), SimpleNamespace(**dict(draft))
                for b in read_visits(con, run_id).values():
                    shop = con.execute('SELECT * FROM rlv2_shop_visits WHERE id=?', (b.visit_id,)).fetchone()
                    if shop is None:
                        raise invalid()
                    value = dict(shop)
                    for key in ('quote', 'before', 'purchases'):
                        value[key] = json.loads(value[key])
                    by_account.setdefault(b.account_id, []).append((b, SimpleNamespace(**value), run, draft))
            wallets = {}
            for raw in con.execute('SELECT * FROM rlv2_bank_wallets'):
                value = dict(raw)
                value['state'] = json.loads(value['state'])
                value['awards'] = json.loads(value['awards']) if 'awards' in value else []
                wallets[value['account_id']] = SimpleNamespace(**value)
            verified = {}
            for account_id in set(by_account) | set(wallets):
                outer = con.execute("SELECT state FROM rlv2_topics WHERE account_id=? AND topic_id='rogue_1'", (account_id,)).fetchone()
                if outer is None:
                    raise invalid()
                wallet = wallets.get(account_id)
                results = {}
                for grant in awards.load(data.rogue_bank, getattr(wallet, 'awards', [])):
                    raw = con.execute('SELECT * FROM rlv2_game_settlements WHERE run_id=?', (grant['run'],)).fetchone()
                    results[grant['run']] = SimpleNamespace(**dict(raw)) if raw is not None else None
                verified[account_id] = verify(data, account_id, wallet, by_account.get(account_id, []),
                                               json.loads(outer[0])['bank'], settlements=results)
            return verified
        except (DomainError, ValueError, KeyError, TypeError, AttributeError) as exc:
            raise ValueError(invalid().message) from exc
