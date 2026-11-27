"""Season-four events, receipt isolation, and atomic settlement on authored data."""

import copy

import pytest
from fastapi.testclient import TestClient
from test_crisis_v2_battle_sessions import begin, pending
from test_crisis_v2_clears import business, finish, map_row, request, setup, source
from test_crisis_v2_comments import compile_rules, detail
from test_crisis_v2_native_battles import source as native_source
from test_crisis_v2_native_battles import start
from test_crisis_v2_persistence import rows
from test_crisis_v2_rules import player

from terralocal.server.domain import crisis_v2
from terralocal.server.domain.errors import DomainError
from terralocal.server.main import create_game_app
from terralocal.server.protocol.crisis_v2_counters import (
    CODEC,
    EVENT_CODEC,
    decode_counters,
    restore_counters,
)
from terralocal.server.services.runtime import Runtime


def definitions():
    return {key: {"id": key, "condition": kind, "paramList": [marker, threshold], "sortId": order}
        for order, (key, kind, marker, threshold) in enumerate([
            ("gravity", "PassWithEventMore", "gravity_change", "5"),
            ("ristar", "PassWithEventMore", "ristar_kill_enemy", "2"),
            ("cbrush", "PassWithEventLess", "cbrush_kill_character", "0")])}


def stats(**counts):
    return {"charStats": [], "extraBattleInfo": {"SIMPLE,,COST": 10} | {
        "SIMPLE,authored-entity," + key: value for key, value in counts.items()}}


def rules_for():
    value = detail()
    value["commentDataMap"] = definitions()
    return compile_rules(value)


def test_legacy_codec_retains_its_exact_canonical_form_and_ignores_new_event_names():
    payload = stats(gravity_change=5, ristar_kill_enemy=2, cbrush_kill_character=0)
    payload["extraBattleInfo"]["DETAILED,actor,cbrush_kill_character"] = -1
    legacy = decode_counters(payload)
    expected = {"codec": CODEC, "characters": [], "enemies": None,
                "extra": [["SIMPLE", "", "COST", None, 10]]}
    assert legacy.canonical() == expected
    assert restore_counters(expected).canonical() == expected
    with pytest.raises(DomainError):
        decode_counters(payload, codec=EVENT_CODEC)


def test_new_counter_shapes_roundtrip_without_changing_the_business_facts():
    payload = stats(gravity_change=5, ristar_kill_enemy=2, cbrush_kill_character=0)
    facts = decode_counters(payload, codec=EVENT_CODEC)
    payload["extraBattleInfo"] = [{"Key": key, "Value": value}
        for key, value in reversed(payload["extraBattleInfo"].items())]
    assert facts.canonical() == decode_counters(payload, codec=EVENT_CODEC).canonical()
    assert facts.codec == EVENT_CODEC
    assert restore_counters(facts.canonical()).canonical() == facts.canonical()
    bad = copy.deepcopy(facts.canonical())
    bad["codec"] = CODEC
    with pytest.raises(ValueError):
        restore_counters(bad)


@pytest.mark.parametrize("marker", ["gravity_change", "ristar_kill_enemy", "cbrush_kill_character"])
@pytest.mark.parametrize("bad", ["detailed", "attribute", "control-character", "negative", "bool"])
def test_wrong_writer_shape_cannot_disappear_or_be_added_to_a_simple_event(marker, bad):
    key, value = "SIMPLE,," + marker, 1
    if bad == "detailed":
        key = "DETAILED,actor," + marker
    elif bad == "attribute":
        key = "ATTRIBUTE,actor," + marker + ",1"
    elif bad == "control-character":
        key = "SIMPLE,actor\n," + marker
    elif bad == "negative":
        value = -1
    else:
        value = True
    with pytest.raises(DomainError) as failure:
        decode_counters({"extraBattleInfo": {key: value}}, codec=EVENT_CODEC)
    assert failure.value.code == "INVALID_CRISIS_V2_COUNTERS"


@pytest.mark.parametrize("gravity,ristar,cbrush,earned", [
    (4, 1, 0, ("cbrush",)), (5, 2, 0, ("gravity", "ristar", "cbrush")),
    (6, 3, 1, ("gravity", "ristar")), (0, 0, 0, ("cbrush",)),
])
def test_event_threshold_boundaries_and_known_zero_use_only_the_admitted_pool(gravity, ristar, cbrush, earned):
    rules, comments = rules_for()
    facts = decode_counters(stats(gravity_change=gravity, ristar_kill_enemy=ristar,
                                  cbrush_kill_character=cbrush), codec=EVENT_CODEC)
    result = comments.evaluate(rules.evaluate(["low"], player(), permanent=True), facts,
                               ("WARRIOR",), cleared=True)
    assert result.earned == earned and result.unavailable == ()


@pytest.mark.parametrize("extra", [None, {}, {"SIMPLE,,cbrush_kill_character": 0}])
def test_missing_end_marker_never_earns_a_zero_or_a_positive_event_comment(extra):
    rules, comments = rules_for()
    facts = decode_counters({"extraBattleInfo": extra}, codec=EVENT_CODEC)
    result = comments.evaluate(rules.evaluate(["low"], player(), permanent=True), facts,
                               ("WARRIOR",), cleared=True)
    assert result.earned == () and result.unavailable == ("gravity", "ristar", "cbrush")


def test_comments_reject_legacy_codec_instead_of_misinterpreting_ignored_new_events():
    rules, comments = rules_for()
    assert comments.counter_codec == EVENT_CODEC
    with pytest.raises(ValueError, match="计数版本"):
        comments.evaluate(rules.evaluate(["low"], player(), permanent=True),
            decode_counters(stats(gravity_change=5, ristar_kill_enemy=2)), ("WARRIOR",), cleared=True)
    assert compile_rules()[1].counter_codec == EVENT_CODEC
    assert compile_rules()[1].counter_codecs == {CODEC, EVENT_CODEC}


def test_entity_bearing_simple_events_aggregate_separate_writers_without_a_second_log_kind():
    rules, comments = rules_for()
    payload = stats(gravity_change=3, ristar_kill_enemy=1)
    payload["extraBattleInfo"] |= {"SIMPLE,second-entity,gravity_change": 2,
                                  "SIMPLE,second-entity,ristar_kill_enemy": 1}
    facts = decode_counters(payload, codec=EVENT_CODEC)
    assert comments.evaluate(rules.evaluate(["low"], player(), permanent=True), facts,
                              ("WARRIOR",), cleared=True).earned == ("gravity", "ristar", "cbrush")
    payload["extraBattleInfo"]["DETAILED,second-entity,ristar_kill_enemy"] = 1
    with pytest.raises(DomainError):
        decode_counters(payload, codec=EVENT_CODEC)


@pytest.mark.parametrize("kind,marker", [
    ("PassWithEventLess", "gravity_change"), ("PassWithEventMore", "cbrush_kill_character"),
    ("PassWithEventMore", "not_build_at_reed"), ("PassWithEventMore", "unverified_event"),
])
def test_new_admission_does_not_generalize_to_unobserved_condition_pairs(kind, marker):
    value = detail()
    value["commentDataMap"] = {"unknown": {
        "id": "unknown", "condition": kind, "paramList": [marker, "1"], "sortId": 0}}
    with pytest.raises(ValueError):
        compile_rules(value)


def test_event_clear_rolls_back_then_replays_after_cold_start_without_a_second_settlement(tmp_path):
    tables = source()
    for entry in tables["crisis_v2_server_table"]["seasons"].values():
        for key, value in entry["info"]["mapDetailDataMap"].items():
            if key.endswith("_p"):
                value["commentDataMap"] = definitions()
    runtime, token, payload = setup(tmp_path, tables=tables)
    try:
        ident = begin(runtime, token, payload)["battleId"]
        body = request(ident, payload, stats=stats(gravity_change=5, ristar_kill_enemy=2))
        before = rows(runtime.database.path)

        def fail(ctx):
            from terralocal.server.domain import crisis_v2_clears

            crisis_v2_clears.finish(ctx, body)
            ctx.session.flush()
            raise DomainError("QA_ROLLBACK", "authored post-event-clear failure")

        with pytest.raises(DomainError, match="post-event-clear"):
            runtime.mutate(token, None, "rollback", "qa-clear", {}, fail)
        assert rows(runtime.database.path) == before
        assert pending(runtime, token, ident).battle.state == "STARTED"
        result = finish(runtime, token, body)
        assert result["newComments"] == ["gravity", "ristar", "cbrush"]
        saved = pending(runtime, token, ident).battle.settlement
        assert saved["counters"]["codec"] == EVENT_CODEC
        assert business(finish(runtime, token, body, "retry")) == business(result)
        conflict = request(ident, payload, stats=stats(gravity_change=4, ristar_kill_enemy=2))
        with pytest.raises(DomainError) as failure:
            finish(runtime, token, conflict, "changed-events")
        assert failure.value.code == "CRISIS_V2_FINISH_CONFLICT"
        runtime.database.close()
        runtime = Runtime(runtime.settings)
        crisis_v2.preflight(runtime.data, runtime.database.path, require_existing_binding=True)
        assert pending(runtime, token, ident).battle.settlement == saved
        assert map_row(runtime)["comments"] == ["gravity", "ristar", "cbrush"]
        assert business(finish(runtime, token, body, "after-restart")) == business(result)
    finally:
        runtime.database.close()


def test_legacy_first_season_receipt_keeps_its_codec_while_new_clears_accept_native_entity_ids(tmp_path):
    tables = source()
    for entry in tables["crisis_v2_server_table"]["seasons"].values():
        for key, value in entry["info"]["mapDetailDataMap"].items():
            if key.endswith("_p"):
                value["commentDataMap"] = {"reed": {"id": "reed", "sortId": 0,
                    "condition": "PassWithEventLess", "paramList": ["not_build_at_reed", "0"]}}
    runtime, token, payload = setup(tmp_path, tables=tables)
    try:
        rules = runtime.data.crisis_v2.comments("season_a", "season_a_p")
        assert rules.counter_codec == EVENT_CODEC
        # Reproduce the old decoder's valid receipt; production does not switch
        # codecs through a request field or an account setting.
        rules.counter_codec = CODEC
        ident = begin(runtime, token, payload)["battleId"]
        body = request(ident, payload, stats=stats(gravity_change=5))
        first = finish(runtime, token, body)
        saved = pending(runtime, token, ident).battle.settlement
        assert saved["counters"]["codec"] == CODEC
        rules.counter_codec = EVENT_CODEC
        runtime.database.close()
        runtime = Runtime(runtime.settings)
        retry = request(ident, payload, stats=stats(gravity_change=1000))
        assert business(finish(runtime, token, retry, "legacy-retry")) == business(first)
        assert pending(runtime, token, ident).battle.settlement == saved
        following = begin(runtime, token, payload, "new-battle")["battleId"]
        result = finish(runtime, token, request(following, payload,
            stats=stats(not_build_at_reed=1)), "new-clear")
        assert result["earnedComments"] == []
        assert pending(runtime, token, following).battle.settlement["counters"]["codec"] == EVENT_CODEC
    finally:
        runtime.database.close()


def test_native_finish_returns_event_comments_and_replays_the_same_response_after_cold_start(tmp_path):
    tables = native_source()
    for entry in tables["crisis_v2_server_table"]["seasons"].values():
        for key, value in entry["info"]["mapDetailDataMap"].items():
            if key.endswith("_p"):
                value["commentDataMap"] = definitions()
    runtime, token, payload = setup(tmp_path, tables=tables)
    try:
        with TestClient(create_game_app(runtime)) as client:
            opened = start(client, token, payload)
            assert opened.status_code == 200
            ident = opened.json()["battleId"]
            body = request(ident, payload, stats=stats(gravity_change=5, ristar_kill_enemy=2)).model_dump()
            headers = {"secret": token, "seqnum": "event-finish"}
            response = client.post("/crisisV2/battleFinish", json=body, headers=headers)
            assert response.status_code == 200, response.text
            first = response.json()
            assert first["commentNew"] == ["gravity", "ristar", "cbrush"]
            assert client.post("/crisisV2/battleFinish", json=body, headers=headers).json() == first
        saved = pending(runtime, token, ident).battle.settlement
        runtime.database.close()
        runtime = Runtime(runtime.settings)
        with TestClient(create_game_app(runtime)) as client:
            response = client.post("/crisisV2/battleFinish", json=body,
                                   headers={"secret": token, "seqnum": "cold-event-finish"})
            assert response.status_code == 200, response.text
            assert response.json()["commentNew"] == first["commentNew"]
            assert response.json()["ts"] == first["ts"]
            assert response.json()["playerDataDelta"] == {"modified": {}, "deleted": {}}
        assert pending(runtime, token, ident).battle.settlement == saved
    finally:
        runtime.database.close()
