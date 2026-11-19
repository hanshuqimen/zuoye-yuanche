"""First-theme ending marks projected from owned, validated settlement rows.

The journal is the sole authority. Reads do not rewrite old outer saves, and
pending finishes, abandoned runs and defeats never earn a completion mark.
Other themes' grade icons are a separate, unimplemented contract.
"""

from terralocal.server.domain.errors import DomainError


def invalid():
    return DomainError("ROGUE_BAND_RECORD_INCOMPATIBLE", "分队结局记录与已验证结算不一致；请保留原存档", 503)


def add(data, counts, run, row):
    from terralocal.server.domain.rogue_completion_rewards import (
        CAPACITY_POLICY,
        DEPLOYMENT_POLICY,
        VARIANT_POLICY,
    )
    from terralocal.server.domain.rogue_completion_rewards import POLICY as NOTIFY_POLICY
    from terralocal.server.domain.rogue_terminal import ENDING_POLICY

    if not row.facts.get("success"):
        return
    detail = data.table("roguelike_topic_table")["details"]["rogue_1"]
    band = data.rogue_initial.band
    # This frozen theme uses counts and has no alias grouping or grade flags.
    # A changed table needs a new adapter rather than a guessed group key.
    if (row.policy_version not in (ENDING_POLICY, NOTIFY_POLICY, VARIANT_POLICY, DEPLOYMENT_POLICY, CAPACITY_POLICY)
            or run.topic_id != "rogue_1"
            or run.mode != "NORMAL" or type(run.grade) is not int or run.grade != 0
            or run.state != "SETTLED" or run.band_id != band
            or row.facts["success"] != 1 or row.facts.get("ending") != "ro_ending_1"
            or detail.get("gameConst", {}).get("initialBandShowGradeFlag") is not False
            or detail.get("bandRef") != {}
            or detail["items"][band].get("itemIconGroupId") is not None):
        raise invalid()
    key = band, row.facts["ending"]
    counts[key] = counts.get(key, 0) + 1
    if counts[key] >= 2**31:
        raise invalid()


def validated_settlement(ctx, run, children=None, *, history=None):
    from terralocal.server.domain.rogue_ending import history_in_session

    if run.account_id != ctx.account_id:
        raise invalid()
    if history is None:
        history = {r.id: row for r, row in history_in_session(ctx)}
    row = history.get(run.id)
    if row is None:
        raise invalid()
    return row


def facts(ctx):
    from terralocal.server.domain.rogue_ending import history_in_session
    counts = {}
    # Keep the account predicate on the authoritative parent, never on a client
    # supplied band, run id or ending field.
    for run, row in history_in_session(ctx):
        add(ctx.data, counts, run, row)
    return counts


def verified_on_disk(data, connection):
    """Called only after ending and retained-run preflight validation."""
    import json
    from types import SimpleNamespace

    tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "rlv2_game_settlements" not in tables:
        return {}
    counts = {}
    for account, topic, mode, grade, state, band, policy, raw in connection.execute(
            "SELECT r.account_id,r.topic_id,r.mode,r.grade,r.state,r.band_id,s.policy_version,s.facts "
            "FROM rlv2_runs r JOIN rlv2_game_settlements s ON s.run_id=r.id WHERE r.topic_id='rogue_1'"):
        add(data, counts.setdefault(account, {}),
            SimpleNamespace(topic_id=topic, mode=mode, grade=grade, state=state, band_id=band),
            SimpleNamespace(policy_version=policy, facts=json.loads(raw)))
    return counts


def project(state, counts):
    expected = {}
    for (band, ending), count in sorted(counts.items()):
        expected.setdefault(band, {})[ending] = count
    record = state["record"]
    if record["bandGrade"] or record["bandCnt"] and record["bandCnt"] != expected:
        raise invalid()
    record["bandCnt"] = expected
    return state
