import pytest
from sqlalchemy import select

from terralocal.server.domain import accounts
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.runtime import Runtime


def batch(client, token, seq, language):
    return client.post("/charBuild/batchSetCharVoiceLan", json={"voiceLan": language},
                       headers={"secret": token, "seqnum": str(seq)})


def test_voice_delta_idempotency_isolation_and_restart(client, runtime, token):
    with runtime.database.transaction() as session:
        accounts.create_account(session, runtime.data, "Other")
        other_token = accounts.login(session, runtime.settings, name="Other")["secret"]
    before = runtime.sync(token)["user"]
    first = batch(client, token, 1, "CN_MANDARIN")
    assert first.status_code == 200
    after = runtime.sync(token)["user"]
    assert after["status"]["globalVoiceLan"] == "CN_MANDARIN"
    assert all(row["voiceLan"] == "CN_MANDARIN" for row in after["troop"]["chars"].values())
    assert apply(before, first.json()["playerDataDelta"]) == after
    assert batch(client, token, 1, "CN_MANDARIN").json() == first.json()
    assert batch(client, token, 1, "JP").status_code == 409
    assert runtime.sync(other_token)["user"]["status"]["globalVoiceLan"] == "JP"
    runtime.database.close()
    restarted = Runtime(runtime.settings)
    try:
        assert restarted.sync(token)["user"] == after
    finally:
        restarted.database.close()


def test_batch_keeps_unavailable_character_voice_but_saves_global_preference(client, runtime, token):
    before = runtime.sync(token)["user"]["troop"]
    assert batch(client, token, 1, "EN").status_code == 200
    after = runtime.sync(token)["user"]
    assert after["troop"] == before and after["status"]["globalVoiceLan"] == "EN"
    snapshot = runtime.sync(token)
    assert batch(client, token, 2, "UNKNOWN").status_code == 400
    assert runtime.sync(token) == snapshot


def test_character_voice_rejects_foreign_ids_unsupported_and_malformed_values(client, runtime, token):
    with runtime.database.transaction() as session:
        other = accounts.create_account(session, runtime.data, "Other")
        own_id = session.scalar(select(m.Operator.id).where(m.Operator.account_id == 1))
        foreign_id = session.scalar(select(m.Operator.id).where(m.Operator.account_id == other.id))
    def request(ids, language, seq):
        return client.post("/charBuild/setCharVoiceLan", json={"charList": ids, "voiceLan": language},
                           headers={"secret": token, "seqnum": str(seq)})
    before = runtime.sync(token)
    assert request([own_id, foreign_id], "CN_MANDARIN", 1).status_code == 404
    assert request([own_id], "EN", 2).status_code == 400
    assert request([True], "JP", 3).status_code == 422
    assert request([], "JP", 4).status_code == 422
    assert runtime.sync(token) == before
    assert request([own_id], "CN_MANDARIN", 5).status_code == 200
    state = runtime.sync(token)["user"]
    assert state["troop"]["chars"][str(own_id)]["voiceLan"] == "CN_MANDARIN"
    assert state["status"]["globalVoiceLan"] == "JP"


def test_future_voice_unlock_is_respected(client, runtime, token):
    # Synthetic data mutation is limited to this fixture's in-memory repository.
    table = runtime.data.table("charword_table")
    table["startTimeWithTypeDict"] = {"CN_MANDARIN": [
        {"charSet": ["char_synthetic"], "timestamp": 1_800_000_010}]}
    assert batch(client, token, 1, "CN_MANDARIN").status_code == 200
    assert next(iter(runtime.sync(token)["user"]["troop"]["chars"].values()))["voiceLan"] == "JP"
    with runtime.database.transaction() as session:
        session.get(m.ServerClockState, 1).fixed_at = 1_800_000_011
    assert batch(client, token, 2, "CN_MANDARIN").status_code == 200
    assert next(iter(runtime.sync(token)["user"]["troop"]["chars"].values()))["voiceLan"] == "CN_MANDARIN"


@pytest.mark.parametrize("mode", ["unknown-language", "missing-character"])
def test_voice_catalog_import_validates_references(mode):
    from conftest import miniature

    from terralocal.server.gamedata.repository import validate_tables

    tables = miniature()
    row = tables["charword_table"]["voiceLangDict"]["char_synthetic"]
    if mode == "unknown-language":
        row["dict"]["UNKNOWN"] = {"voiceLangType": "UNKNOWN"}
    else:
        tables["charword_table"]["voiceLangDict"].clear()
    with pytest.raises(ValueError, match="语音"):
        validate_tables(tables)
