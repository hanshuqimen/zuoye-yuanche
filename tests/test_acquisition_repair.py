"""Audited legacy corrections and the formerly blocked ten-pull transaction."""

import pytest
from fastapi.testclient import TestClient
from test_headhunting import head_runtime, login, pull  # noqa: F401 -- shared validated fixture
from test_native_training import training_runtime  # noqa: F401 -- shared validated fixture
from test_recruitment import recruit_runtime  # noqa: F401 -- dependency of head_runtime

from terralocal.admin.app import create_admin_app
from terralocal.server.domain import accounts
from terralocal.server.domain.acquisitions import VERIFIED, acquire_standard
from terralocal.server.domain.context import Context
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.services.runtime import Runtime


def command(char_id="char_tier_6", count=1, **changes):
    return {"accountId": 1, "action": "set-acquisition-count", "id": char_id,
            "value": count, "title": "Verified local creation receipt: one grant", **changes}


def test_verified_legacy_correction_is_audited_and_does_not_grant_rewards(request):
    runtime = request.getfixturevalue("training_runtime")
    with runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 1)
        op, _ = ctx.acquire_operator("char_tier_6")
        op.potential = 5
        session.delete(session.get(m.OperatorAcquisition, (1, op.char_id, "STANDARD")))
    token = login(runtime)
    before = runtime.sync(token)["user"]
    with TestClient(create_admin_app(runtime), base_url="http://127.0.0.1:8080") as client:
        csrf = client.get("/api/session").json()["csrf"]
        assert client.post("/api/gm", json=command()).status_code == 403
        response = client.post("/api/gm", json=command(), headers={"x-csrf-token": csrf})
        assert response.status_code == 200
        assert response.json()["acquisition"]["basis"] == VERIFIED
    after = runtime.sync(token)["user"]
    assert after["troop"] == before["troop"] and after["inventory"] == before["inventory"]
    for key in ("gold", "diamondShard", "freeDiamond", "hggShard", "lggShard"):
        assert after["status"][key] == before["status"][key]
    runtime.database.close()
    restarted = Runtime(runtime.settings)
    try:
        with restarted.database.transaction() as session:
            row = session.get(m.OperatorAcquisition, (1, "char_tier_6", "STANDARD"))
            assert (row.count, row.basis) == (1, VERIFIED)
            audit = session.query(m.AuditLog).filter_by(action="set-acquisition-count").one()
            assert audit.account_id == 1 and audit.detail["outcome"]["evidence"] == command()["title"]
            drawn = acquire_standard(Context(session, restarted.data, 1), "char_tier_6")
            assert drawn["isNew"] is False
            assert drawn["itemGet"][-1] == {"id": "4004", "count": 10, "type": "HGG_SHD"}
            assert drawn["potent"] == {"delta": 1, "now": 1} and row.count == 2
    finally:
        restarted.database.close()


@pytest.mark.parametrize("changes,status", [({"value": 0}, 400), ({"title": None}, 400),
    ({"title": "  "}, 400), ({"value": True}, 422), ({"id": "char_tier_5"}, 404)])
def test_invalid_correction_rolls_back_and_leaves_no_audit_or_counter(request, changes, status):
    runtime = request.getfixturevalue("training_runtime")
    with runtime.database.transaction() as session:
        Context(session, runtime.data, 1).acquire_operator("char_tier_6")
        session.delete(session.get(m.OperatorAcquisition, (1, "char_tier_6", "STANDARD")))
    before = runtime.sync(login(runtime))["user"]
    with TestClient(create_admin_app(runtime), base_url="http://127.0.0.1:8080") as client:
        csrf = client.get("/api/session").json()["csrf"]
        response = client.post("/api/gm", json=command(**changes), headers={"x-csrf-token": csrf})
        assert response.status_code == status
    assert runtime.sync(login(runtime))["user"] == before
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.OperatorAcquisition, (1, "char_tier_6", "STANDARD")) is None
        assert session.query(m.AuditLog).count() == 0


def test_correction_cannot_reduce_recorded_count_or_change_another_stream(request):
    runtime = request.getfixturevalue("training_runtime")
    with runtime.database.transaction() as session:
        Context(session, runtime.data, 1).acquire_operator("char_tier_6", count=2)
        other = accounts.create_account(session, runtime.data, "Other")
        session.add(m.OperatorAcquisition(account_id=1, char_id="char_tier_6", stream="CLASSIC",
                                         count=8, basis=VERIFIED))
    with TestClient(create_admin_app(runtime), base_url="http://127.0.0.1:8080") as client:
        csrf = client.get("/api/session").json()["csrf"]
        for payload, expected in ((command(), 409), (command(accountId=other.id), 404), (command(count=6), 200)):
            assert client.post("/api/gm", json=payload, headers={"x-csrf-token": csrf}).status_code == expected
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.OperatorAcquisition, (1, "char_tier_6", "STANDARD")).count == 6
        assert session.get(m.OperatorAcquisition, (1, "char_tier_6", "CLASSIC")).count == 8
        assert session.get(m.OperatorAcquisition, (other.id, "char_tier_6", "STANDARD")) is None
        assert session.query(m.AuditLog).count() == 1


def test_legacy_six_star_ten_pull_rolls_back_then_succeeds_once_after_correction(request, monkeypatch):
    import random

    runtime = request.getfixturevalue("head_runtime")
    token = login(runtime)
    with runtime.database.transaction() as session:
        Context(session, runtime.data, 1).acquire_operator("char_recruit_5")
        session.delete(session.get(m.OperatorAcquisition, (1, "char_recruit_5", "STANDARD")))
        session.get(m.Currency, (1, "4003")).balance = 10_000
    before = runtime.sync(token)
    monkeypatch.setattr(random.Random, "choices", lambda *args, **kwargs: [5])
    with TestClient(create_game_app(runtime)) as game:
        failed = pull(game, token, 1, count=10)
        assert failed.status_code == 503
        assert failed.json()["error"]["code"] == "ACQUISITION_HISTORY_INCOMPLETE"
        assert runtime.sync(token) == before
        with runtime.database.transaction(write=False) as session:
            assert session.query(m.GachaHistory).count() == session.query(m.GachaPity).count() == 0
        with TestClient(create_admin_app(runtime), base_url="http://127.0.0.1:8080") as admin:
            csrf = admin.get("/api/session").json()["csrf"]
            assert admin.post("/api/gm", json=command("char_recruit_5"),
                              headers={"x-csrf-token": csrf}).status_code == 200
        drawn = pull(game, token, 1, count=10)
        assert drawn.status_code == 200
        assert pull(game, token, 1, count=10).json() == drawn.json()
    results = drawn.json()["gachaResultList"]
    assert [r["itemGet"][-1]["count"] for r in results] == [10] * 5 + [15] * 5
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.Currency, (1, "4003")).balance == 6200
        assert session.get(m.Currency, (1, "4004")).balance == 125
        assert session.get(m.OperatorAcquisition, (1, "char_recruit_5", "STANDARD")).count == 11
        assert session.query(m.GachaHistory).count() == 10

