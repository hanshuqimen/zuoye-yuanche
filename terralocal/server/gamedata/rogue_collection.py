"""First-theme archive references, without interpreting unlock prose as rules."""

from dataclasses import dataclass
from types import MappingProxyType

from terralocal.server.gamedata.repository import fingerprint

POLICY = "rogue1-relic-archive-references-v1"


def invalid():
    return ValueError("首主题收藏品图鉴引用与匹配数据不一致")


@dataclass(frozen=True)
class RelicArchiveEntry:
    id: str
    enrollment: str | None
    special: bool
    group: int
    sort: int
    order: str
    unlock_description: str | None


class FirstThemeRelicArchive:
    """An archive entry is neither an unlocked effect nor a natural stock pool."""

    def __init__(self, data):
        data.rogue_topics.topic("rogue_1")
        entries = {}
        try:
            detail = data.table("roguelike_topic_table")["details"]["rogue_1"]
            source = detail["archiveComp"]["relic"]["relic"]
            if type(source) is not dict or not 0 < len(source) <= 4096:
                raise invalid()
            for key, row in source.items():
                item = detail["items"][key]
                if (type(key) is not str or not 0 < len(key) <= 128 or type(row) is not dict
                        or set(row) != {"relicId", "enrollId", "isSpRelic", "relicGroupId", "relicSortId", "orderId"}
                        or row["relicId"] != key or item.get("id") != key or item.get("type") != "RELIC"
                        or detail["relics"][key].get("id") != key
                        or row["enrollId"] is not None and (type(row["enrollId"]) is not str
                            or row["enrollId"] not in detail["enrolls"])
                        or type(row["isSpRelic"]) is not bool
                        or any(type(row[f]) is not int or not 0 <= row[f] < 2**31
                               for f in ("relicGroupId", "relicSortId"))
                        or type(row["orderId"]) is not str or not 0 < len(row["orderId"]) <= 32
                        or item.get("unlockCondDesc") is not None and type(item["unlockCondDesc"]) is not str):
                    raise invalid()
                entries[key] = RelicArchiveEntry(key, row["enrollId"], row["isSpRelic"], row["relicGroupId"],
                    row["relicSortId"], row["orderId"], item.get("unlockCondDesc"))
        except (KeyError, TypeError, AttributeError) as exc:
            raise invalid() from exc
        self.entries = MappingProxyType(entries)
        self.fingerprint = fingerprint({"policy": POLICY, "data": data.manifest["hash"], "entries": {
            key: {"enrollment": row.enrollment, "special": row.special, "group": row.group,
                  "sort": row.sort, "order": row.order, "unlock_description": row.unlock_description}
            for key, row in entries.items()}})
