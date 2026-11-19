"""Costume ownership boundaries, using synthetic data and optional frozen JSON."""

import copy
import json
from pathlib import Path

import pytest
from conftest import miniature

from terralocal.server.domain import accounts, skins
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata import GameData, import_data
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.protocol.sync import SyncDataAssembler
from terralocal.server.services.runtime import Runtime

CHAR = "char_synthetic"
OTHER = "char_second"
PATCH = "char_synthetic_patch"
RESERVED = "char_synthetic_reserved"
COSTUME = f"{CHAR}@shop#1"
EVENT = f"{CHAR}@event#1"
PATCH_COSTUME = f"{PATCH}@event#1"
FROZEN = "f44199a7d34a82bdbb232674db3a3cdf9d7958230217fce3960ccafd351b7406"


def skin_catalog():
    def row(skin_id, char_id, is_buy, *, template=None):
        return {"skinId": skin_id, "charId": char_id, "tmplId": template, "isBuySkin": is_buy,
                "displaySkin": {"skinName": "Synthetic Costume" if is_buy else None}}

    entries = {key: row(key, CHAR, False) for key in (f"{CHAR}#1", f"{CHAR}#1+", f"{CHAR}#2")}
    entries.update({COSTUME: row(COSTUME, CHAR, True), EVENT: row(EVENT, CHAR, True),
                    PATCH_COSTUME: row(PATCH_COSTUME, CHAR, True, template=PATCH),
                    f"{PATCH}#2": row(f"{PATCH}#2", CHAR, False, template=PATCH),
                    f"{OTHER}#1": row(f"{OTHER}#1", OTHER, False),
                    f"{OTHER}@shop#1": row(f"{OTHER}@shop#1", OTHER, True),
                    "token_synthetic#1": row("token_synthetic#1", "token_synthetic", False)})
    return {"charSkins": entries,
            "buildinEvolveMap": {CHAR: {"0": f"{CHAR}#1", "1": f"{CHAR}#1+", "2": f"{CHAR}#2"},
                                 OTHER: {"0": f"{OTHER}#1"}},
            "buildinPatchMap": {CHAR: {PATCH: f"{PATCH}#2"}}}


@pytest.fixture
def skin_runtime(runtime, tmp_path):
    tables = miniature()
    tables["character_table"][CHAR]["phases"].append({"maxLevel": 5, "evolveCost": None})
    tables["character_table"][OTHER] = copy.deepcopy(tables["character_table"][CHAR])
    # Frozen Amiya templates live outside character_table. Ownership must be
    # resolvable through buildinPatchMap without adding a fake ordinary char.
    tables["character_table"][RESERVED] = {**copy.deepcopy(tables["character_table"][CHAR]),
                                            "isNotObtainable": True}
    tables["character_table"]["token_synthetic"] = {"name": "Synthetic Token", "isNotObtainable": True}
    words = tables["charword_table"]
    words["voiceLangDict"][OTHER] = copy.deepcopy(words["voiceLangDict"][CHAR])
    words["charDefaultTypeDict"][OTHER] = "JP"
    tables["skin_table"] = skin_catalog()
    source = tmp_path / "skin-source"
    source.mkdir()
    for name, table in tables.items():
        (source / f"{name}.json").write_text(json.dumps(table), "utf-8")
    manifest = import_data(source, runtime.settings.data_dir / "cache")
    runtime.settings.gamedata_hash = manifest["hash"]
    runtime.settings.save()
    runtime.data = GameData(runtime.settings.data_dir / "cache" / manifest["hash"])
    return runtime


def test_definition_preserves_real_owner_instead_of_skin_id_prefix(skin_runtime):
    assert PATCH not in skin_runtime.data.characters
    costume = skins.definition(skin_runtime.data, PATCH_COSTUME, char_id=CHAR)
    assert costume["itemType"] == "CHAR_SKIN"
    assert (costume["itemId"], costume["skinId"], costume["charId"], costume["tmplId"]) == (
        PATCH_COSTUME, PATCH_COSTUME, CHAR, PATCH)
    assert costume["isBuySkin"] is True
    assert costume["builtinPhases"] == [] and costume["builtinPatchId"] is None
    with pytest.raises(DomainError) as failed:
        skins.definition(skin_runtime.data, PATCH_COSTUME, char_id=PATCH)
    assert failed.value.code == "SKIN_CHARACTER_MISMATCH"


def test_default_evolution_and_patch_metadata_do_not_assert_payment_or_unlock(skin_runtime):
    for phase, suffix in ((0, "#1"), (1, "#1+"), (2, "#2")):
        row = skins.definition(skin_runtime.data, CHAR + suffix)
        assert row["builtinPhases"] == [phase]
        assert row["isBuySkin"] is False and row["builtinPatchId"] is None
    patch = skins.definition(skin_runtime.data, f"{PATCH}#2")
    assert patch["charId"] == CHAR and patch["builtinPhases"] == []
    assert patch["tmplId"] == patch["builtinPatchId"] == PATCH
    assert skins.definition(skin_runtime.data, COSTUME)["tmplId"] is None


def test_patch_costume_can_be_owned_without_unlocking_or_equipping_its_template(skin_runtime):
    with skin_runtime.database.transaction() as session:
        ctx = Context(session, skin_runtime.data, 1)
        before = SyncDataAssembler(ctx).assemble()
        op = ctx.rows(m.Operator)[0]
        result = skins.grant(ctx, PATCH_COSTUME, operator_id=op.id, char_id=CHAR)
        after = SyncDataAssembler(ctx).assemble()
        assert result == {"id": PATCH_COSTUME, "type": "CHAR_SKIN", "count": 1}
        assert after["skin"]["characterSkins"] == {PATCH_COSTUME: 1}
        assert after["troop"] == before["troop"] and after["status"] == before["status"]
        assert PATCH not in ctx.data.characters and op.skin == f"{CHAR}#1"
        assert session.get(m.InventoryItem, (1, PATCH_COSTUME)) is None


def test_grant_without_operator_uses_only_owned_skin_and_does_not_equip(skin_runtime):
    with skin_runtime.database.transaction() as session:
        ctx = Context(session, skin_runtime.data, 1)
        before = SyncDataAssembler(ctx).assemble()
        assert all(op.char_id != OTHER for op in ctx.rows(m.Operator))
        result = skins.grant(ctx, f"{OTHER}@shop#1", char_id=OTHER)
        after = SyncDataAssembler(ctx).assemble()
        assert result == {"id": f"{OTHER}@shop#1", "type": "CHAR_SKIN", "count": 1}
        assert after["skin"]["characterSkins"] == {f"{OTHER}@shop#1": 1}
        assert after["troop"] == before["troop"] and after["inventory"] == before["inventory"]
        assert after["status"] == before["status"]
        assert session.get(m.InventoryItem, (1, f"{OTHER}@shop#1")) is None
        assert session.get(m.Currency, (1, f"{OTHER}@shop#1")) is None


def test_duplicate_grants_preserve_first_time_and_do_not_compensate(skin_runtime):
    with skin_runtime.database.transaction() as session:
        ctx = Context(session, skin_runtime.data, 1)
        before = SyncDataAssembler(ctx).assemble()
        skins.grant(ctx, EVENT)
        first = session.get(m.OwnedSkin, (1, EVENT))
        obtained = first.obtained_at
        ctx.now += 50
        skins.grant(ctx, EVENT)
        assert session.get(m.OwnedSkin, (1, EVENT)) is first
        assert first.obtained_at == obtained and len(ctx.rows(m.OwnedSkin)) == 1
        after = SyncDataAssembler(ctx).assemble()
        assert after["status"] == before["status"] and after["inventory"] == before["inventory"]
    with skin_runtime.database.transaction() as session:
        ctx = Context(session, skin_runtime.data, 1)
        ctx.now += 100
        skins.grant(ctx, EVENT)
        assert session.get(m.OwnedSkin, (1, EVENT)).obtained_at == obtained
        assert len(ctx.rows(m.OwnedSkin)) == 1


def test_grant_and_receipt_replay_produce_matching_sync_delta(skin_runtime, token):
    before = skin_runtime.sync(token)["user"]

    def action(ctx):
        return {"items": [skins.grant(ctx, COSTUME)]}

    result = skin_runtime.mutate(token, None, "skin-once", "synthetic-skin-reward", {}, action)
    assert skin_runtime.mutate(token, None, "skin-once", "synthetic-skin-reward", {}, action) == result
    after = skin_runtime.sync(token)["user"]
    assert apply(before, result["playerDataDelta"]) == after
    assert after["skin"]["characterSkins"] == {COSTUME: 1}
    assert COSTUME not in after["inventory"]


def test_accounts_have_independent_skin_ownership_and_foreign_operator_is_rejected(skin_runtime):
    with skin_runtime.database.transaction() as session:
        other = accounts.create_account(session, skin_runtime.data, "SkinOther")
        ours = Context(session, skin_runtime.data, 1)
        foreign = Context(session, skin_runtime.data, other.id)
        foreign_op = foreign.rows(m.Operator)[0]
        skins.grant(foreign, COSTUME, operator_id=foreign_op.id)
        assert SyncDataAssembler(ours).assemble()["skin"]["characterSkins"] == {}
        with pytest.raises(DomainError) as failed:
            skins.grant(ours, COSTUME, operator_id=foreign_op.id)
        assert failed.value.code == "UNKNOWN_OPERATOR"
        assert session.get(m.OwnedSkin, (1, COSTUME)) is None
        skins.grant(ours, COSTUME)
        assert session.get(m.OwnedSkin, (1, COSTUME)) is not session.get(m.OwnedSkin, (other.id, COSTUME))


def test_wrong_operator_and_catalog_owner_claims_are_rejected_before_writes(skin_runtime):
    with skin_runtime.database.transaction() as session:
        ctx = Context(session, skin_runtime.data, 1)
        op = ctx.rows(m.Operator)[0]
        for claims in ({"operator_id": op.id}, {"char_id": CHAR}):
            with pytest.raises(DomainError) as failed:
                skins.grant(ctx, f"{OTHER}@shop#1", **claims)
            assert failed.value.code == "SKIN_CHARACTER_MISMATCH"
        assert not ctx.rows(m.OwnedSkin)


def test_mismatched_context_session_cannot_grant_to_another_account(skin_runtime):
    with skin_runtime.database.transaction() as session:
        other = accounts.create_account(session, skin_runtime.data, "SkinSessionOther")
        foreign = m.LocalSession(account_id=other.id)
        ctx = Context(session, skin_runtime.data, 1, local_session=foreign)
        with pytest.raises(DomainError) as failed:
            skins.grant(ctx, COSTUME)
        assert failed.value.code == "ACCOUNT_MISMATCH"
        assert not ctx.rows(m.OwnedSkin)


@pytest.mark.parametrize("skin_id", [None, True, 1, [], "", " ", "char_ synthetic@shop#1", "s" * 129])
def test_invalid_skin_ids_fail_explicitly(skin_runtime, skin_id):
    with pytest.raises(DomainError) as failed:
        skins.definition(skin_runtime.data, skin_id)
    assert failed.value.code == "INVALID_SKIN_ID"


@pytest.mark.parametrize("count", [True, False, None, -1, 0, 2, 1.0, "1"])
def test_invalid_skin_quantities_never_write_ownership(skin_runtime, count):
    with skin_runtime.database.transaction() as session:
        ctx = Context(session, skin_runtime.data, 1)
        with pytest.raises(DomainError) as failed:
            skins.grant(ctx, COSTUME, count)
        assert failed.value.code == "INVALID_REWARD"
        assert not ctx.rows(m.OwnedSkin)


@pytest.mark.parametrize("skin_id", [f"{CHAR}#1", f"{CHAR}#1+", f"{CHAR}#2", f"{PATCH}#2"])
def test_builtin_grants_cannot_bypass_operator_or_patch_progression(skin_runtime, skin_id):
    with skin_runtime.database.transaction() as session:
        ctx = Context(session, skin_runtime.data, 1)
        with pytest.raises(DomainError) as failed:
            skins.grant(ctx, skin_id)
        assert failed.value.code == "BUILTIN_SKIN"
        assert not ctx.rows(m.OwnedSkin)
        assert ctx.rows(m.Operator)[0].evolve_phase == 0
        assert ctx.rows(m.Operator)[0].skin == f"{CHAR}#1"


@pytest.mark.parametrize("case", ["row-id", "owner", "flag", "template", "display", "overlap"])
def test_inconsistent_definition_is_an_explicit_data_error(skin_runtime, case):
    table = skin_runtime.data.table("skin_table")
    row = table["charSkins"][COSTUME]
    if case == "row-id":
        row["skinId"] = EVENT
    elif case == "owner":
        row["charId"] = "char_missing"
    elif case == "flag":
        row["isBuySkin"] = 1
    elif case == "template":
        row["tmplId"] = OTHER
    elif case == "display":
        row["displaySkin"] = None
    else:
        table["buildinEvolveMap"][CHAR]["1"] = COSTUME
    with pytest.raises(DomainError) as failed:
        skins.definition(skin_runtime.data, COSTUME)
    assert failed.value.code == "GAMEDATA_INVALID" and failed.value.status == 503


@pytest.mark.parametrize("case", ["missing-map", "missing-default", "default-id", "default-owner",
                                 "default-template", "default-is-costume", "unknown-template"])
def test_patch_template_requires_a_matching_source_mapping_and_default_row(skin_runtime, case):
    table = skin_runtime.data.table("skin_table")
    row = table["charSkins"][PATCH_COSTUME]
    builtin = table["charSkins"][f"{PATCH}#2"]
    if case == "missing-map":
        del table["buildinPatchMap"][CHAR][PATCH]
    elif case == "missing-default":
        del table["charSkins"][f"{PATCH}#2"]
    elif case == "default-id":
        builtin["skinId"] = COSTUME
    elif case == "default-owner":
        builtin["charId"] = OTHER
    elif case == "default-template":
        builtin["tmplId"] = CHAR
    elif case == "default-is-costume":
        table["buildinPatchMap"][CHAR][PATCH] = COSTUME
    else:
        row["tmplId"] = "char_missing_patch"
    with pytest.raises(DomainError) as failed:
        skins.definition(skin_runtime.data, PATCH_COSTUME)
    assert failed.value.code == "GAMEDATA_INVALID" and failed.value.status == 503


def test_unknown_summon_unobtainable_and_unmapped_skins_are_rejected(skin_runtime):
    data = skin_runtime.data
    with pytest.raises(DomainError) as unknown:
        skins.definition(data, "char_synthetic@unknown#1")
    assert unknown.value.code == "UNKNOWN_SKIN"
    with pytest.raises(DomainError) as summon:
        skins.definition(data, "token_synthetic#1")
    assert summon.value.code == "NOT_CHARACTER_SKIN"
    data.table("skin_table")["charSkins"][COSTUME]["charId"] = RESERVED
    with pytest.raises(DomainError) as unobtainable:
        skins.definition(data, COSTUME)
    assert unobtainable.value.code == "UNOBTAINABLE_OPERATOR"
    del data.table("skin_table")["buildinEvolveMap"][CHAR]["2"]
    with pytest.raises(DomainError) as unmapped:
        skins.definition(data, f"{CHAR}#2")
    assert unmapped.value.code == "SKIN_UNLOCK_RULE_UNVERIFIED"


def test_failure_after_cost_and_skin_grant_rolls_back_all_state(skin_runtime, token):
    before = skin_runtime.sync(token)

    def failed(ctx):
        ctx.consume([{"id": "4001", "count": 10}])
        skins.grant(ctx, COSTUME)
        skins.grant(ctx, "char_synthetic@unknown#1")
        return {}

    with pytest.raises(DomainError):
        skin_runtime.mutate(token, None, "skin-failed", "synthetic-skin-reward", {}, failed)
    assert skin_runtime.sync(token) == before
    with skin_runtime.database.transaction() as session:
        assert not Context(session, skin_runtime.data, 1).rows(m.OwnedSkin)


def test_owned_skin_survives_runtime_restart(skin_runtime, token):
    with skin_runtime.database.transaction() as session:
        ctx = Context(session, skin_runtime.data, 1)
        skins.grant(ctx, COSTUME)
        obtained = session.get(m.OwnedSkin, (1, COSTUME)).obtained_at
    expected = skin_runtime.sync(token)
    skin_runtime.database.close()
    restarted = Runtime(skin_runtime.settings)
    try:
        assert restarted.sync(token) == expected
        with restarted.database.transaction() as session:
            assert session.get(m.OwnedSkin, (1, COSTUME)).obtained_at == obtained
        assert restarted.database.integrity() == "ok"
    finally:
        restarted.database.close()


def test_frozen_nondefault_skin_definitions_and_amiya_template_relationships():
    directory = Path(__file__).resolve().parents[1] / "data/cache" / FROZEN
    if not (directory / "manifest.json").is_file():
        pytest.skip("Optional frozen GameData is not installed")
    data = GameData(directory, expected_hash=FROZEN)
    table = data.table("skin_table")
    assert fingerprint(table) == "474351b92055e27a880c4d9303b9458c38a327366af9b19f6db6d0b2721cf877"
    assert fingerprint(data.characters) == data.manifest["tables"]["character_table"]
    nondefault = [skins.definition(data, key) for key, row in table["charSkins"].items() if row["isBuySkin"]]
    assert len(nondefault) == 520
    assert all(not row["builtinPhases"] and row["builtinPatchId"] is None for row in nondefault)
    amiya = skins.definition(data, "char_1001_amiya2@casc#1", char_id="char_002_amiya")
    assert amiya["charId"] == "char_002_amiya" and amiya["tmplId"] == "char_1001_amiya2"
    assert "char_1001_amiya2" not in data.characters and "char_1037_amiya3" not in data.characters
    patch_costumes = [row for row in nondefault if row["tmplId"] not in {None, row["charId"]}]
    assert {row["skinId"] for row in patch_costumes} == {
        "char_1001_amiya2@casc#1", "char_1001_amiya2@sale#16", "char_1037_amiya3@sale#13"}
    default = skins.definition(data, "char_1001_amiya2#2")
    assert default["builtinPatchId"] == "char_1001_amiya2" and default["isBuySkin"] is False
    event = table["charSkins"]["char_002_amiya@epoque#4"]
    assert event["isBuySkin"] is True and event["displaySkin"]["obtainApproach"] == "活动获得"
