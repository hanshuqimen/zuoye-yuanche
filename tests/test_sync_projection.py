"""Pending writes, membership changes and rollback remain visible in sync views."""

import json

import pytest
from sqlalchemy import select

from terralocal.server.domain import accounts
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply, diff
from terralocal.server.protocol.sync import SyncDataAssembler


@pytest.mark.parametrize(("old", "new"), [(True, 1), (0, False), (1, 1.0)])
def test_delta_preserves_a_changed_scalar_wire_type(old, new):
    before = {"settings": {"value": old}}
    after = {"settings": {"value": new}}
    changes = diff(before, after)
    assert type(changes["modified"]["settings"]["value"]) is type(new)
    assert json.dumps(apply(before, changes)) == json.dumps(after)


def test_saved_json_type_change_replaces_the_list_in_the_write_reply(runtime, token):
    old_flags = [{"enabled": True}, [0]]
    new_flags = [{"enabled": 1}, [False]]
    with runtime.database.transaction() as session:
        profile = session.get(m.PlayerProfile, 1)
        profile.flags = {**profile.flags, "story": {"fixtureFlags": old_flags}}
    before = runtime.sync(token)["user"]
    assert json.dumps(before["status"]["flags"]["fixtureFlags"]) == json.dumps(old_flags)

    def replace_flags(ctx):
        ctx.profile.flags = {**ctx.profile.flags, "story": {"fixtureFlags": new_flags}}
        return {}

    result = runtime.mutate(token, None, "fixture-flag-types", "fixture-change-types", {}, replace_flags)
    after = runtime.sync(token)["user"]
    changes = result["playerDataDelta"]
    assert json.dumps(changes["modified"]["status"]["flags"]["fixtureFlags"]) == json.dumps(new_flags)
    assert json.dumps(after["status"]["flags"]["fixtureFlags"]) == json.dumps(new_flags)
    assert json.dumps(apply(before, changes), sort_keys=True) == json.dumps(after, sort_keys=True)


def test_pending_operator_skill_and_currency_changes_are_in_the_same_snapshot(runtime):
    with runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 1)
        before = SyncDataAssembler(ctx).assemble()
        op = ctx.rows(m.Operator)[0]
        skill = session.scalar(select(m.OperatorSkill).where(m.OperatorSkill.operator_id == op.id))
        op.level, op.exp, op.trust, op.locked = 2, 30, 15, True
        skill.mastery, skill.training_complete_at = 1, ctx.now + 60
        session.get(m.Currency, (1, "4001")).balance = 735
        # No explicit flush: the view must include pending domain changes.
        after = SyncDataAssembler(ctx).assemble()
        character = after["troop"]["chars"][str(op.id)]
        assert (character["level"], character["exp"], character["favorPoint"], character["starMark"]) == (2, 30, 15, 1)
        assert character["skills"][0]["specializeLevel"] == 1
        assert character["skills"][0]["completeUpgradeTime"] == ctx.now + 60
        assert character["skills"][0]["state"] == 1
        assert after["status"]["gold"] == 735
        assert before["troop"]["chars"][str(op.id)]["level"] == 1
        assert apply(before, diff(before, after)) == after


def test_same_context_requeries_inserted_and_deleted_membership(runtime):
    with runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 1)
        before = SyncDataAssembler(ctx).assemble()
        item = m.InventoryItem(account_id=1, item_id="material", count=7)
        skin = m.OwnedSkin(account_id=1, skin_id="synthetic-alt", obtained_at=ctx.now)
        session.add_all([item, skin])
        inserted = SyncDataAssembler(ctx).assemble()
        assert inserted["inventory"]["material"] == 7
        assert inserted["skin"]["characterSkins"]["synthetic-alt"] == 1
        assert "material" not in before["inventory"]
        session.delete(item)
        session.delete(skin)
        deleted = SyncDataAssembler(ctx).assemble()
        assert "material" not in deleted["inventory"]
        assert "synthetic-alt" not in deleted["skin"]["characterSkins"]
        assert apply(inserted, diff(inserted, deleted)) == deleted == before


def test_inventory_furniture_and_story_counts_are_values(runtime):
    with runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 1)
        session.add_all([m.InventoryItem(account_id=1, item_id="material", count=7),
                         m.OwnedFurniture(account_id=1, item_id="synthetic-furniture", count=3),
                         m.StoryCompletion(account_id=1, story_id="synthetic_intro", completed_at=ctx.now)])
        snapshot = SyncDataAssembler(ctx).assemble()
        assert snapshot["inventory"]["material"] == 7
        assert snapshot["building"]["furniture"]["synthetic-furniture"] == {"count": 3, "inUse": 0}
        assert snapshot["status"]["flags"]["synthetic_intro"] == 1


def test_skill_projection_and_all_account_rows_exclude_other_accounts(runtime):
    with runtime.database.transaction() as session:
        other = accounts.create_account(session, runtime.data, "OtherProjection")
        ours = Context(session, runtime.data, 1)
        foreign = Context(session, runtime.data, other.id)
        foreign_op = foreign.rows(m.Operator)[0]
        foreign_skill = session.scalar(select(m.OperatorSkill).where(m.OperatorSkill.operator_id == foreign_op.id))
        foreign_skill.mastery = 3
        foreign.change_item("4001", 99)
        foreign.change_item("material", 8)
        session.add(m.OwnedSkin(account_id=other.id, skin_id="foreign-skin", obtained_at=foreign.now))
        snapshot = SyncDataAssembler(ours).assemble()
        assert str(foreign_op.id) not in snapshot["troop"]["chars"]
        assert len(snapshot["troop"]["chars"]) == 1
        assert next(iter(snapshot["troop"]["chars"].values()))["skills"][0]["specializeLevel"] == 0
        assert snapshot["status"]["gold"] == 1000
        assert "material" not in snapshot["inventory"]
        assert "foreign-skin" not in snapshot["skin"]["characterSkins"]


@pytest.mark.parametrize("change", ["operator", "new-item", "delete-skin"])
def test_snapshot_flush_then_failure_rolls_back_every_view(runtime, token, change):
    if change == "delete-skin":
        with runtime.database.transaction() as session:
            session.add(m.OwnedSkin(account_id=1, skin_id="synthetic-alt", obtained_at=1_800_000_000))
    before = runtime.sync(token)
    with pytest.raises(DomainError, match="injected rollback"):
        with runtime.database.transaction() as session:
            ctx = Context(session, runtime.data, 1)
            if change == "operator":
                ctx.rows(m.Operator)[0].level = 2
            elif change == "new-item":
                session.add(m.InventoryItem(account_id=1, item_id="material", count=5))
            else:
                session.delete(ctx.rows(m.OwnedSkin)[0])
            changed = SyncDataAssembler(ctx).assemble()
            assert changed != before["user"]
            raise DomainError("INJECTED", "injected rollback")
    assert runtime.sync(token) == before
