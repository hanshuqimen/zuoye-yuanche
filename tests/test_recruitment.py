"""Recruitment rules, durable outcomes, isolation and transactional retries."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest
from conftest import miniature
from fastapi.testclient import TestClient
from sqlalchemy import select

from terralocal.config import Settings
from terralocal.server.domain import accounts
from terralocal.server.gamedata import import_data
from terralocal.server.gamedata.repository import validate_tables
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.persistence.migrations import REVISION
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def recruit_runtime(tmp_path):
    tables = miniature()
    for item_id, kind in {"7001": "TKT_RECRUIT", "7002": "TKT_INST_FIN",
                          "4004": "HGG_SHD", "4005": "LGG_SHD"}.items():
        tables["item_table"]["items"][item_id] = {"itemId": item_id, "name": item_id, "itemType": kind}
    initial = tables["character_table"]["char_synthetic"]
    initial.update(profession="WARRIOR", position="MELEE", tagList=["Output"])
    for rarity in range(6):
        char_id = f"char_recruit_{rarity}"
        tables["character_table"][char_id] = {
            **initial, "name": f"Recruit {rarity}", "rarity": f"TIER_{rarity + 1}"}
        tables["charword_table"]["voiceLangDict"][char_id] = {
            "dict": {"JP": {"voiceLangType": "JP"}}}
        tables["charword_table"]["charDefaultTypeDict"][char_id] = "JP"
    tables["gamedata_const"]["initRecruitTagList"] = [1, 2, 3, 4, 5]
    tables["stage_table"]["stages"]["main_00-02"] = {
        **tables["stage_table"]["stages"]["test_1"], "stageId": "main_00-02"}
    tables["gacha_table"] = {
        "gachaTags": [{"tagId": tag, "tagName": name} for tag, name in {
            1: "Guard", 2: "Sniper", 3: "Defender", 4: "Medic", 5: "Supporter",
            9: "Melee", 11: "Top", 14: "Senior", 19: "Output"}.items()],
        "recruitPool": {"recruitConstants": {"maxRecruitTime": 540,
                                             "tagPriceList": {str(i): i * 10 for i in range(4)}},
                        "recruitTimeTable": [{"timeLength": 10, "recruitPrice": 5},
                                             {"timeLength": 540, "recruitPrice": 30}]},
        "recruitRarityTable": {"10": {"rarityStart": 0, "rarityEnd": 3},
                              "540": {"rarityStart": 2, "rarityEnd": 4}},
        "specialTagRarityTable": {"11": [5], "14": [4]},
        "recruitDetail": "\n-----\n".join("★" * (i + 1) + "\\nRecruit " + str(i) for i in range(6)),
    }
    source = tmp_path / "source"
    source.mkdir()
    for name, content in tables.items():
        (source / f"{name}.json").write_text(json.dumps(content), "utf-8")
    manifest = import_data(source, tmp_path / "data" / "cache")
    settings = Settings(data_dir=tmp_path / "data", gamedata_hash=manifest["hash"], tls=False)
    settings.save()
    runtime = Runtime(settings)
    with runtime.database.transaction() as session:
        clock = session.get(m.ServerClockState, 1)
        clock.mode, clock.fixed_at = "fixed", 1_800_000_000
        accounts.create_account(session, runtime.data, "Doctor")
        session.add(m.StageProgress(account_id=1, stage_id="main_00-02", unlocked=True, stars=3))
        session.add_all([m.InventoryItem(account_id=1, item_id="7001", count=10),
                         m.InventoryItem(account_id=1, item_id="7002", count=10)])
    yield runtime
    runtime.database.close()


@pytest.fixture
def recruit_client(recruit_runtime):
    with recruit_runtime.database.transaction() as session:
        token = accounts.login(session, recruit_runtime.settings, name="Doctor")["secret"]
    with TestClient(create_game_app(recruit_runtime)) as client:
        yield client, token


def request(pair, action, body=None, seq=1):
    client, token = pair
    return client.post("/gacha/" + action, headers={"secret": token, "seqnum": str(seq)}, json=body or {})


def start_body(slot=0, tags=None, duration=32400):
    return {"slotId": slot, "tagList": [1] if tags is None else tags, "specialTagId": -1, "duration": duration}


def test_native_slot_contract_initialization_and_progress_gate(recruit_runtime, recruit_client):
    runtime, (_, token) = recruit_runtime, recruit_client
    before = runtime.sync(token)["user"]
    response = request(recruit_client, "syncNormalGacha")
    assert response.status_code == 200
    after = runtime.sync(token)["user"]
    assert apply(before, response.json()["playerDataDelta"]) == after
    slots = after["recruit"]["normal"]["slots"]
    assert list(slots) == ["0", "1", "2", "3"]
    assert [slot["state"] for slot in slots.values()] == [1, 1, 0, 0]
    assert all(slot["tags"] == [1, 2, 3, 4, 5] and slot["selectTags"] == [] for slot in slots.values())
    first_revision = runtime.sync(token)["revision"]
    assert request(recruit_client, "syncNormalGacha").status_code == 200
    assert runtime.sync(token)["revision"] == first_revision
    with runtime.database.transaction() as session:
        accounts.create_account(session, runtime.data, "Unprogressed")
        other_token = accounts.login(session, runtime.settings, name="Unprogressed")["secret"]
    client, _ = recruit_client
    other = (client, other_token)
    assert request(other, "syncNormalGacha").status_code == 200
    assert {r["state"] for r in runtime.sync(other_token)["user"]["recruit"]["normal"]["slots"].values()} == {0}


def test_start_deducts_once_and_result_does_not_reroll_on_restart(recruit_runtime, recruit_client):
    runtime, (_, token) = recruit_runtime, recruit_client
    before = runtime.sync(token)["user"]
    response = request(recruit_client, "normalGacha", start_body())
    assert response.status_code == 200
    after = runtime.sync(token)["user"]
    assert apply(before, response.json()["playerDataDelta"]) == after
    assert after["status"]["gold"] == 960 and after["status"]["recruitLicense"] == 9
    slot = after["recruit"]["normal"]["slots"]["0"]
    assert slot["state"] == 2 and slot["durationInSec"] == 32400
    assert slot["maxFinishTs"] == slot["realFinishTs"] == slot["startTs"] + 32400
    assert request(recruit_client, "normalGacha", start_body()).json() == response.json()
    assert request(recruit_client, "finishNormalGacha", {"slotId": 0}, seq=2).status_code == 409
    with runtime.database.transaction(write=False) as session:
        selected = session.get(m.RecruitSlot, (1, 0)).result_char_id
    runtime.database.close()
    restarted = Runtime(runtime.settings)
    try:
        assert restarted.sync(token)["user"] == after
        with restarted.database.transaction() as session:
            assert session.get(m.RecruitSlot, (1, 0)).result_char_id == selected
            session.get(m.ServerClockState, 1).fixed_at += 32400
        with TestClient(create_game_app(restarted)) as fresh:
            result = request((fresh, token), "finishNormalGacha", {"slotId": 0}, seq=3)
            assert result.status_code == 200 and result.json()["charGet"]["charId"] == selected
    finally:
        restarted.database.close()


def test_expedite_and_concurrent_finish_cannot_duplicate_rewards(recruit_runtime, recruit_client):
    runtime, (_, token) = recruit_runtime, recruit_client
    assert request(recruit_client, "normalGacha", start_body()).status_code == 200
    before = runtime.sync(token)["user"]
    boost = request(recruit_client, "boostNormalGacha", {"slotId": 0, "buy": 0}, seq=2)
    assert boost.status_code == 200
    after = runtime.sync(token)["user"]
    assert apply(before, boost.json()["playerDataDelta"]) == after
    slot = after["recruit"]["normal"]["slots"]["0"]
    assert slot["state"] == 3 and slot["realFinishTs"] == 1_800_000_000
    assert slot["maxFinishTs"] == 1_800_032_400 and after["status"]["instantFinishTicket"] == 9
    assert request(recruit_client, "boostNormalGacha", {"slotId": 0, "buy": 0}, seq=3).status_code == 409
    before = runtime.sync(token)["user"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: request(recruit_client, "finishNormalGacha", {"slotId": 0}, seq=4), range(8)))
    assert all(result.status_code == 200 for result in results)
    assert all(result.json() == results[0].json() for result in results)
    after = runtime.sync(token)["user"]
    assert apply(before, results[0].json()["playerDataDelta"]) == after
    assert request(recruit_client, "finishNormalGacha", {"slotId": 0}, seq=5).status_code == 409
    with runtime.database.transaction(write=False) as session:
        assert len(session.scalars(select(m.GachaHistory)).all()) == 1
        assert len(session.scalars(select(m.DomainEvent).where(m.DomainEvent.event_type == "RecruitCompleted")).all()) == 1


@pytest.mark.parametrize("body,status", [(start_body(tags=[1, 1]), 400), (start_body(tags=[19]), 400),
                                       (start_body(duration=601), 400), (start_body(slot=2), 409),
                                       ({**start_body(), "slotId": True}, 422)])
def test_invalid_commands_leave_inventory_and_save_unchanged(recruit_runtime, recruit_client, body, status):
    request(recruit_client, "syncNormalGacha")
    token = recruit_client[1]
    before = recruit_runtime.sync(token)
    response = request(recruit_client, "normalGacha", body)
    assert response.status_code == status
    assert recruit_runtime.sync(token) == before


def test_insufficient_resources_and_assembly_failure_roll_back(recruit_runtime, recruit_client, monkeypatch):
    runtime, (_, token) = recruit_runtime, recruit_client
    with runtime.database.transaction() as session:
        session.get(m.InventoryItem, (1, "7001")).count = 0
    before = runtime.sync(token)
    assert request(recruit_client, "normalGacha", start_body()).status_code == 400
    assert runtime.sync(token) == before
    with runtime.database.transaction() as session:
        session.get(m.InventoryItem, (1, "7001")).count = 10
    before = runtime.sync(token)
    from terralocal.server.protocol.sync import SyncDataAssembler

    original = SyncDataAssembler.assemble
    calls = 0

    def fail_second(self):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("Synthetic response failure")
        return original(self)

    with monkeypatch.context() as patch:
        patch.setattr(SyncDataAssembler, "assemble", fail_second)
        with pytest.raises(RuntimeError, match="Synthetic response failure"):
            request(recruit_client, "normalGacha", start_body(), seq=2)
    assert runtime.sync(token) == before


@pytest.mark.parametrize("tags,expected", [([11], "char_recruit_5"), ([14], "char_recruit_4"),
                                         ([11, 14], "char_recruit_5")])
def test_nine_hour_special_guarantees_use_only_recruit_pool(recruit_runtime, recruit_client, tags, expected):
    request(recruit_client, "syncNormalGacha")
    with recruit_runtime.database.transaction() as session:
        session.get(m.RecruitSlot, (1, 0)).available_tags = [11, 14, 1, 9, 19]
    assert request(recruit_client, "normalGacha", start_body(tags=tags)).status_code == 200
    assert request(recruit_client, "boostNormalGacha", {"slotId": 0, "buy": 0}, seq=2).status_code == 200
    result = request(recruit_client, "finishNormalGacha", {"slotId": 0}, seq=3)
    assert result.status_code == 200 and result.json()["charGet"]["charId"] == expected


def test_cancel_does_not_refund_and_backup_preserves_active_outcome(recruit_runtime, recruit_client):
    runtime, (_, token) = recruit_runtime, recruit_client
    assert request(recruit_client, "normalGacha", start_body()).status_code == 200
    active = runtime.sync(token)["user"]
    saved = BackupService(runtime).create()
    assert request(recruit_client, "cancelNormalGacha", {"slotId": 0}, seq=2).status_code == 200
    canceled = runtime.sync(token)["user"]
    assert canceled["status"]["recruitLicense"] == active["status"]["recruitLicense"] == 9
    assert canceled["status"]["gold"] == active["status"]["gold"] == 960
    assert canceled["recruit"]["normal"]["slots"]["0"]["state"] == 1
    BackupService(runtime).restore(saved["name"])
    assert runtime.sync(token)["user"] == active


def test_story_revision_upgrades_recruitment_without_replacing_save(recruit_runtime, recruit_client):
    runtime, (_, token) = recruit_runtime, recruit_client
    before = runtime.sync(token)["user"]
    runtime.database.close()
    with sqlite3.connect(runtime.settings.database_path) as conn:
        conn.execute("DROP TABLE operator_acquisitions")
        conn.execute("DROP TABLE owned_furniture")
        conn.execute("ALTER TABLE battle_sessions DROP COLUMN native_context")
        conn.execute("UPDATE alembic_version SET version_num='0004_story_completion'")
        for column in ("policy_version", "gamedata_hash"):
            conn.execute(f"ALTER TABLE gacha_pity DROP COLUMN {column}")
        for column in ["duration_seconds", "max_finishes_at", "retained_tags", "result_char_id",
                       "policy_version", "gamedata_hash"]:
            conn.execute(f"ALTER TABLE recruit_slots DROP COLUMN {column}")
    restarted = Runtime(runtime.settings)
    try:
        assert restarted.sync(token)["user"] == before
        with restarted.database.transaction(write=False) as session:
            assert session.connection().exec_driver_sql("SELECT version_num FROM alembic_version").scalar() == REVISION
        assert restarted.database.integrity() == "ok"
    finally:
        restarted.database.close()


@pytest.mark.parametrize("kind", ["tag", "name", "permit"])
def test_import_rejects_broken_recruit_references_before_admission(recruit_runtime, kind):
    data = recruit_runtime.data
    tables = {name: deepcopy(data.table(name)) for name in data.manifest["tables"]}
    if kind == "tag":
        tables["gacha_table"]["gachaTags"][0]["tagId"] = True
    elif kind == "name":
        tables["gacha_table"]["recruitDetail"] = tables["gacha_table"]["recruitDetail"].replace("Recruit 0", "Missing")
    else:
        del tables["item_table"]["items"]["7001"]
    with pytest.raises(ValueError):
        validate_tables(tables)


@pytest.mark.parametrize("field,value", [("available_tags", [True, 2, 3, 4, 5]),
                                         ("available_tags", None), ("state", "INVALID")])
def test_corrupt_recruit_save_fails_explicitly_without_a_server_error(recruit_runtime, recruit_client, field, value):
    with recruit_runtime.database.transaction() as session:
        setattr(session.get(m.RecruitSlot, (1, 0)), field, value)
    response = request(recruit_client, "syncNormalGacha")
    assert response.status_code == 503 and response.json()["error"]["code"] == "INVALID_RECRUIT_STATE"
