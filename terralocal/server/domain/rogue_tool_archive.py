"""Permanent tool discovery from validated grants, never current equipment.

Native ArchiveTrapModel reads collect.activeTool: missing/state0 is locked,
state1 is unattained, and state2 exposes obtained descriptions. Availability
is limited to the reviewed, no-enrollment tool catalog and its topic opening.
"""

from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata import rogue_support_tools as rules


def invalid():
    return DomainError("ROGUE_TOOL_ARCHIVE_INCOMPATIBLE", "工具图鉴与已核对的获得来源不一致；请保留原存档", 503)


def available(data):
    if data is None or "roguelike_topic_table" not in data.manifest["tables"]:
        return False
    details = data.table("roguelike_topic_table")["details"]
    return "rogue_1" in details and bool(rules.SOURCES.keys() & details["rogue_1"]["items"].keys())


def attained(replayed):
    return frozenset(grant.item_id for grant in replayed.support_tool_grants) if replayed is not None else frozenset()


def project(data, state, found, at):
    saved = state["collect"]["activeTool"]
    try:
        entries = data.rogue_support_tools.entries if available(data) else {}
        if type(at) is not int or not 0 <= at < 2**63 or not set(found) <= entries.keys():
            raise invalid()
        for key, row in saved.items():
            if (key not in entries or row["progress"] or row["state"] == 2 and key not in found
                    or row["state"] == 1 and at < entries[key].opens_at):
                raise invalid()
        # A read projects eligibility/discovery; it never backfills the saved
        # outer JSON, creates a grant, or equips a tool in the current run.
        for key, entry in entries.items():
            saved[key] = {"state": 2 if key in found else int(at >= entry.opens_at), "progress": []}
        return state
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        raise invalid() from exc
