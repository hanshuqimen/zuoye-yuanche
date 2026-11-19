"""Synthetic contracts shaped by observed native ZIP journal and proxy requests."""

import copy
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import miniature
from fastapi.testclient import TestClient
from sqlalchemy import delete
from test_native_battle_finish import complete, encoded
from test_native_battle_start import begin, body, login
from test_native_replay import cleared, journal, packed, save

from terralocal.config import Settings
from terralocal.server.domain import accounts
from terralocal.server.gamedata import import_data
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.protocol.sync import SyncDataAssembler
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def proxy_runtime(tmp_path):
    tables = miniature()
    for stage in tables["stage_table"]["stages"].values():
        stage.update(stageType="MAIN", difficulty="NORMAL", diffGroup="NONE",
                     apProtectTimes=0, isPredefined=False, isStagePatch=False)
    tables["stage_table"]["apProtectZoneInfo"] = {}
    tables["stage_table"]["stages"]["tr_06"] = {
        **tables["stage_table"]["stages"]["test_1"], "stageId": "tr_06", "canBattleReplay": False}
    tables["character_table"]["char_noskill"] = {
        **copy.deepcopy(tables["character_table"]["char_synthetic"]), "skills": []}
    tables["charword_table"]["voiceLangDict"]["char_noskill"] = copy.deepcopy(
        tables["charword_table"]["voiceLangDict"]["char_synthetic"])
    tables["character_table"]["char_synthetic"]["skills"].append({
        "skillId": "second", "unlockCond": {"phase": "PHASE_1", "level": 1}})
    tables["skill_table"]["second"] = {}
    source = tmp_path / "source"
    source.mkdir()
    for name, content in tables.items():
        (source / f"{name}.json").write_text(json.dumps(content), "utf-8")
    manifest = import_data(source, tmp_path / "data/cache")
    settings = Settings(data_dir=tmp_path / "data", gamedata_hash=manifest["hash"], tls=False)
    settings.save()
    runtime = Runtime(settings)
    runtime.drop_rules = {"test_1": {"rewards": [], "first_rewards": []},
                          "test_2": {"rewards": [], "first_rewards": []}}
    with runtime.database.transaction() as session:
        clock = session.get(m.ServerClockState, 1)
        clock.mode, clock.fixed_at = "fixed", 1_800_000_000
        accounts.create_account(session, runtime.data, "Doctor")
        session.get(m.SanityState, 1).current = 60
        session.add(m.StageProgress(account_id=1, stage_id="tr_06", stars=2,
                                   unlocked=True, start_count=1, clear_count=1))
    yield runtime
    runtime.database.close()


def proxy_body():
    payload = body()
    payload["isReplay"] = 1
    payload["squad"]["name"] = None
    payload["squad"]["slots"] += [None] * 11
    return payload


def record(client, token):
    source = cleared(client, token)
    assert save(client, token, source).status_code == 200
    return source


def test_native_null_name_proxy_uses_independent_members_and_current_growth(proxy_runtime):
    runtime, token = proxy_runtime, login(proxy_runtime)
    with TestClient(create_game_app(runtime)) as client:
        source = record(client, token)
        with runtime.database.transaction() as session:
            session.execute(delete(m.SquadSlot).where(m.SquadSlot.account_id == 1))
            operator = session.get(m.Operator, 1)
            operator.level, operator.skin = 2, "current-skin"
            saved_slots = session.query(m.SquadSlot).count()
        before = runtime.sync(token)["user"]
        with ThreadPoolExecutor(max_workers=4) as workers:
            replies = list(workers.map(lambda _: begin(client, token, proxy_body(), "proxy"), range(6)))
        assert all(reply.status_code == 200 and reply.json() == replies[0].json() for reply in replies)
        response = replies[0].json()
        after = runtime.sync(token)["user"]
        assert apply(before, response["playerDataDelta"]) == after
        assert after["status"]["ap"] == before["status"]["ap"] - 6
        with runtime.database.transaction(write=False) as session:
            active = session.get(m.BattleSession, response["battleId"])
            assert active.squad_snapshot == [{"charInstId": 1, "skillIndex": 0,
                "charId": "char_synthetic", "level": 2, "evolvePhase": 0}]
            assert active.native_context["formation_mode"] == "AUTO_BATTLE"
            assert active.native_context["replay_source_battle_id"] == source
            assert session.query(m.SquadSlot).count() == saved_slots == 0
            assert session.get(m.StageReplay, (1, "test_1")).battle_id == source
            assert session.query(m.BattleSession).count() == 2
        finish = encoded(response["battleId"], state=3)
        assert complete(client, token, finish, "proxy-finish").status_code == 200
        paid = runtime.sync(token)
        assert complete(client, token, finish, "proxy-finish-again").status_code == 200
        assert runtime.sync(token)["user"] == paid["user"]
        assert paid["user"]["status"]["freeDiamond"] == after["status"]["freeDiamond"]
    before_restart = runtime.sync(token)
    runtime.database.close()
    reopened = Runtime(runtime.settings)
    try:
        with TestClient(create_game_app(reopened)) as client:
            assert begin(client, token, proxy_body(), "proxy").json() == response
        assert reopened.sync(token) == before_restart
    finally:
        reopened.database.close()


@pytest.mark.parametrize("damage,status,code", [
    ("gate", 409, "REPLAY_LOCKED"), ("rank", 409, "REPLAY_UNAVAILABLE"),
    ("absent", 404, "REPLAY_NOT_FOUND"), ("fingerprint", 503, "INVALID_REPLAY_STATE"),
    ("operator", 404, "UNKNOWN_OPERATOR"), ("foreign-operator", 404, "UNKNOWN_OPERATOR"),
    ("skill", 409, "REPLAY_SQUAD_CONFLICT"),
    ("module", 409, "REPLAY_SQUAD_CONFLICT"), ("squad-id", 409, "REPLAY_SQUAD_CONFLICT"),
    ("duplicate", 409, "REPLAY_SQUAD_CONFLICT"), ("hole", 409, "REPLAY_SQUAD_CONFLICT"),
    ("ap", 400, "INSUFFICIENT_SANITY"),
])
def test_rejected_proxy_start_preserves_ap_records_and_progress(proxy_runtime, damage, status, code):
    runtime, token = proxy_runtime, login(proxy_runtime)
    payload = proxy_body()
    with TestClient(create_game_app(runtime)) as client:
        record(client, token)
        with runtime.database.transaction() as session:
            if damage == "gate":
                session.get(m.StageProgress, (1, "tr_06")).stars = 0
            elif damage == "rank":
                session.get(m.StageProgress, (1, "test_1")).stars = 2
            elif damage == "absent":
                session.delete(session.get(m.StageReplay, (1, "test_1")))
            elif damage == "fingerprint":
                row = session.get(m.StageReplay, (1, "test_1"))
                row.replay = {**row.replay, "sha256": "0" * 64}
            elif damage == "ap":
                session.get(m.SanityState, 1).current = 5
            elif damage == "foreign-operator":
                accounts.create_account(session, runtime.data, "Other")
        if damage == "operator":
            payload["squad"]["slots"][0]["charInstId"] = 9999
        elif damage == "foreign-operator":
            payload["squad"]["slots"][0]["charInstId"] = 2
        elif damage == "skill":
            payload["squad"]["slots"][0]["skillIndex"] = 1
        elif damage == "module":
            payload["squad"]["slots"][0]["currentEquip"] = "unexpected-module"
        elif damage == "squad-id":
            payload["squad"]["squadId"] = "1"
        elif damage == "duplicate":
            payload["squad"]["slots"][1] = copy.deepcopy(payload["squad"]["slots"][0])
        elif damage == "hole":
            payload["squad"]["slots"][1] = payload["squad"]["slots"][0]
            payload["squad"]["slots"][0] = None
        before = runtime.sync(token)
        response = begin(client, token, payload, "rejected-proxy")
        assert response.status_code == status and response.json()["error"]["code"] == code
        assert runtime.sync(token) == before
        with runtime.database.transaction(write=False) as session:
            assert session.query(m.BattleSession).count() == 1


def test_distinct_proxy_starts_and_failed_response_do_not_duplicate_or_leak_ap(proxy_runtime, monkeypatch):
    runtime, token = proxy_runtime, login(proxy_runtime)
    with TestClient(create_game_app(runtime), raise_server_exceptions=False) as client:
        record(client, token)
        before = runtime.sync(token)
        original, calls = SyncDataAssembler.assemble, 0

        def fail_after_proxy(self):
            nonlocal calls
            calls += 1
            if calls == 2:
                assert self.ctx.session.query(m.BattleSession).count() == 2
                raise RuntimeError("Synthetic proxy response assembly failure")
            return original(self)

        with monkeypatch.context() as patch:
            patch.setattr(SyncDataAssembler, "assemble", fail_after_proxy)
            assert begin(client, token, proxy_body(), "rollback").status_code == 500
        assert runtime.sync(token) == before
        with ThreadPoolExecutor(max_workers=2) as workers:
            replies = list(workers.map(lambda key: begin(client, token, proxy_body(), key), ["a", "b"]))
        assert sorted(reply.status_code for reply in replies) == [200, 409]
        assert runtime.sync(token)["user"]["status"]["ap"] == before["user"]["status"]["ap"] - 6


@pytest.mark.parametrize("no_skill_wire_index", [None, -1, 0])
def test_observed_no_skill_journal_minus_one_and_omitted_request_default(proxy_runtime, no_skill_wire_index):
    runtime, token = proxy_runtime, login(proxy_runtime)
    with runtime.database.transaction() as session:
        session.get(m.Operator, 1).char_id = "char_noskill"
    content = journal()
    content["journal"]["squad"][0].update(skillId=None, skillIndex=-1)
    with TestClient(create_game_app(runtime)) as client:
        source = cleared(client, token)
        assert save(client, token, source, packed(content)).status_code == 200
        payload = proxy_body()
        if no_skill_wire_index is None:
            payload["squad"]["slots"][0].pop("skillIndex")
        else:
            payload["squad"]["slots"][0]["skillIndex"] = no_skill_wire_index
        assert begin(client, token, payload, "no-skill-proxy").status_code == 200


@pytest.mark.parametrize("change,code", [
    ({"charInstId": 9999}, "REPLAY_SQUAD_CONFLICT"),
    ({"skillId": "second", "skillIndex": 1}, "REPLAY_SKILL_CONFLICT"),
    ({"isAssistChar": True}, "REPLAY_SQUAD_CONFLICT"),
    ({"uniequipId": "unverified-module", "uniequipLevel": 1}, "REPLAY_MODULE_UNSUPPORTED"),
    ({"tmplId": "unsupported-template"}, "REPLAY_TEMPLATE_UNSUPPORTED"),
])
def test_save_cannot_advertise_a_foreign_or_incompatible_proxy(proxy_runtime, change, code):
    runtime, token = proxy_runtime, login(proxy_runtime)
    content = journal()
    content["journal"]["squad"][0].update(change)
    with TestClient(create_game_app(runtime)) as client:
        source = cleared(client, token)
        before = runtime.sync(token)
        response = save(client, token, source, packed(content))
        assert response.status_code in {409, 501} and response.json()["error"]["code"] == code
        assert runtime.sync(token) == before
        with runtime.database.transaction(write=False) as session:
            assert session.query(m.StageReplay).count() == 0


@pytest.mark.parametrize("change", [
    {"charInstId": True}, {"skillIndex": "0"}, {"uniequipLevel": True},
    {"uniequipLevel": 4}, {"isAssistChar": 1}, {"tmplId": ""},
    {"skillId": ""}, {"uniequipId": None}, "duplicate", "not-member", "missing",
])
def test_malformed_journal_members_never_create_proxy_flag(proxy_runtime, change):
    runtime, token = proxy_runtime, login(proxy_runtime)
    content = journal()
    members = content["journal"]["squad"]
    if isinstance(change, dict):
        members[0].update(change)
    elif change == "duplicate":
        members.append(copy.deepcopy(members[0]))
    elif change == "not-member":
        members[0] = 1
    else:
        members[0].pop("charInstId")
    with TestClient(create_game_app(runtime)) as client:
        source = cleared(client, token)
        before = runtime.sync(token)
        response = save(client, token, source, packed(content))
        assert response.status_code == 400 and response.json()["error"]["code"] == "INVALID_NATIVE_REPLAY"
        assert runtime.sync(token) == before
        with runtime.database.transaction(write=False) as session:
            assert session.query(m.StageReplay).count() == 0
