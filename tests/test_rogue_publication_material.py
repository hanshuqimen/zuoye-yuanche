"""Bound pure publication reuse; current JSON and live-row checks still run."""

import pytest
from fastapi.testclient import TestClient
from test_rogue_content_publication import activate
from test_rogue_content_publication import content_runtime as content_runtime
from test_roguelike_initial import post
from test_roguelike_state import rows

from terralocal.server.domain import rogue_content, rogue_shops, rogue_visits
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m

pytest_plugins = ("test_rogue_battle_loot",)


def observe_scope(monkeypatch):
    original = rogue_content.publish
    exits = []
    def observed(ctx, run, draft):
        try:
            return original(ctx, run, draft)
        finally:
            exits.append((rogue_content._MATERIAL in ctx.session.info,
                          rogue_content._PUBLISHING in ctx.session.info))
    monkeypatch.setattr(rogue_content, "publish", observed)
    return exits


def test_one_material_allocation_during_publication_but_no_reuse_after_scope(content_runtime, monkeypatch):
    runtime, token = content_runtime
    original_allocate, original_publish = rogue_content.allocate, rogue_content.publish
    during, publication_allocations, all_allocations = [], [], []
    def allocate(*args, **kwargs):
        all_allocations.append(1)
        if during:
            publication_allocations.append(1)
        return original_allocate(*args, **kwargs)
    def publish(*args, **kwargs):
        during.append(True)
        try:
            return original_publish(*args, **kwargs)
        finally:
            during.pop()
    monkeypatch.setattr(rogue_content, "allocate", allocate)
    monkeypatch.setattr(rogue_content, "publish", publish)
    exits = observe_scope(monkeypatch)
    activate(runtime, token)
    assert len(publication_allocations) == 1 and exits == [(False, False)]
    with runtime.database.transaction(write=False) as session:
        run, draft = session.query(m.RogueTopicRun).one(), session.query(m.RogueMapDraft).one()
        before = len(all_allocations)
        rogue_content.validate(runtime.data, run, draft)
        rogue_content.validate(runtime.data, run, draft)
        assert len(all_allocations) == before + 2


@pytest.mark.parametrize("damage", ["plan", "graph"])
def test_untracked_json_edits_cannot_hit_publication_material(content_runtime, monkeypatch, damage):
    runtime, token = content_runtime
    saved = rows(runtime.database.path)
    original = rogue_visits.prepare
    injected = []
    def prepare(ctx, *args, **kwargs):
        result = original(ctx, *args, **kwargs)
        if not injected:
            draft = ctx.session.query(m.RogueMapDraft).one()
            if damage == "plan":
                draft.plan["assignments"][0]["candidate"] = "injected-without-flagging-orm"
            else:
                draft.graph["zones"]["1"]["nodes"]["0"]["visibility"] = "FOG"
            assert draft not in ctx.session.dirty
            injected.append(True)
        return result
    monkeypatch.setattr(rogue_visits, "prepare", prepare)
    exits = observe_scope(monkeypatch)
    with TestClient(create_game_app(runtime), raise_server_exceptions=False) as client:
        result = post(client, token, "finishEvent", {}, "material-json-" + damage)
        assert result.status_code == 503, result.text
    assert injected == [True] and exits == [(False, False)]
    assert rows(runtime.database.path) == saved


@pytest.mark.parametrize("damage", ["scenes-deleted", "shop-price", "battle-spec"])
def test_final_checks_reject_live_row_damage_and_roll_back_all_prepared_content(content_runtime, monkeypatch, damage):
    runtime, token = content_runtime
    saved = rows(runtime.database.path)
    original = rogue_shops.prepare
    injected = []
    def prepare(ctx, *args, **kwargs):
        result = original(ctx, *args, **kwargs)
        if damage == "scenes-deleted":
            assert ctx.session.query(m.RogueSceneVisit).delete(synchronize_session="fetch") == 2
            injected.append(True)
        elif damage == "shop-price":
            row = ctx.session.query(m.RogueShopVisit).one()
            row.quote["offers"][0]["price"] += 1
            assert row not in ctx.session.dirty
            injected.append(row)  # Keep this clean ORM object alive until the final query.
        else:
            row = ctx.session.query(m.RogueBattleLootPlan).one()
            row.spec["eligibility"].append("injected-unknown")
            assert row not in ctx.session.dirty
            injected.append(row)
        return result
    monkeypatch.setattr(rogue_shops, "prepare", prepare)
    exits = observe_scope(monkeypatch)
    with TestClient(create_game_app(runtime), raise_server_exceptions=False) as client:
        result = post(client, token, "finishEvent", {}, "material-live-" + damage)
        assert result.status_code == 503, result.text
    assert len(injected) == 1 and exits == [(False, False)]
    assert rows(runtime.database.path) == saved
