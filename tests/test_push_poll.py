from sqlalchemy import select

from terralocal.server.domain import accounts
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.runtime import Runtime


def poll(client, token):
    return client.post("/account/syncPushMessage", json={}, headers={"secret": token})


def test_poll_reports_current_mail_flags_without_claiming_rewards(client, runtime, token):
    with runtime.database.transaction() as session:
        for row in session.scalars(select(m.Mail).where(m.Mail.account_id == 1)):
            row.read = True
    before = runtime.sync(token)["user"]
    with runtime.database.transaction() as session:
        other = accounts.create_account(session, runtime.data, "Other")
        session.add(m.Mail(account_id=other.id, title="Foreign", body="", created_at=1))
        session.add(m.Mail(account_id=1, title="Expired", body="", created_at=1, expires_at=2))
    response = poll(client, token)
    assert response.status_code == 200 and response.json()["code"] == 200
    flags = response.json()["playerDataDelta"]["modified"]["pushFlags"]
    # Frozen PlayerPushFlags fields are Boolean, while status is Int64.
    assert all(type(flags[key]) is bool for key in ("hasGifts", "hasClues", "hasFriendRequest", "hasFreeLevelGP"))
    assert flags["hasGifts"] is False
    assert apply(before, response.json()["playerDataDelta"]) == runtime.sync(token)["user"]
    with runtime.database.transaction() as session:
        session.add(m.Mail(account_id=1, title="Local", body="", created_at=1,
                            rewards=[{"id": "material", "count": 3}]))
    assert poll(client, token).json()["playerDataDelta"]["modified"]["pushFlags"]["hasGifts"] is True
    assert "material" not in runtime.sync(token)["user"]["inventory"]


def test_poll_recovers_sanity_updates_presence_and_survives_restart(client, runtime, token):
    with runtime.database.transaction() as session:
        session.get(m.SanityState, 1).current = 2
    before = runtime.sync(token)["user"]
    with runtime.database.transaction() as session:
        session.get(m.ServerClockState, 1).fixed_at += 720
    response = poll(client, token)
    after = runtime.sync(token)["user"]
    assert after["status"]["ap"] == 4
    assert after["status"]["lastOnlineTs"] == before["status"]["lastOnlineTs"] + 720
    assert apply(before, response.json()["playerDataDelta"]) == after
    runtime.database.close()
    restarted = Runtime(runtime.settings)
    try:
        assert restarted.sync(token)["user"] == after
    finally:
        restarted.database.close()


def test_poll_rejects_wrong_authentication_stage_and_unobserved_fields(client, runtime, token):
    with runtime.database.transaction() as session:
        sdk_token = accounts.login(session, runtime.settings, name="Doctor", kind="sdk")["secret"]
    assert poll(client, "invalid").status_code == 401
    assert poll(client, sdk_token).status_code == 401
    assert client.post("/account/syncPushMessage", json={"messages": []},
                       headers={"secret": token}).status_code == 422
    assert token not in (runtime.settings.data_dir / "logs/requests.jsonl").read_text("utf-8")
