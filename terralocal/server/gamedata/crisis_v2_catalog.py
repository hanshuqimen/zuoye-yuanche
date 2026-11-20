"""Version-bound local Crisis V2 information source; no runtime network reads.

The inclusive table calendar is an explicit local server policy. The native
client's current-season cache contract does not establish server date rules.
An active shared-table season without an imported info source is an error.
"""

import json
from dataclasses import dataclass
from types import MappingProxyType, SimpleNamespace

from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.crisis_v2 import CLIENT_ELF_SHA256, CrisisV2MapRules
from terralocal.server.gamedata.repository import fingerprint

SERVER_TABLE = "crisis_v2_server_table"
CALENDAR = "shared-table-inclusive-end-v1"
POLICY = "cn-2.7.71-crisis-v2-information-v1"
INFO_FIELDS = {"seasonId", "mapStageDataMap", "mapDetailDataMap", "achievementDataMap", "seasonConst"}


def _id(value):
    if type(value) is not str or not 1 <= len(value) <= 160 or "\0" in value:
        raise ValueError("危机合约信息标识非法")
    return value


def _time(value):
    if type(value) is not int or not 0 <= value < 2**63 - 1:
        raise ValueError("危机合约信息时间非法")
    return value


@dataclass(frozen=True)
class SeasonInfo:
    season_id: str
    start: int
    end: int


class CrisisV2Catalog:
    def __init__(self, data):
        source = data.table(SERVER_TABLE)
        if (type(source) is not dict or set(source) != {
                "schema", "data_version", "client_elf_sha256", "calendar_policy", "seasons"}
                or type(source["schema"]) is not int or source["schema"] != 1
                or source["data_version"] != data.manifest["version"]
                or source["client_elf_sha256"] != CLIENT_ELF_SHA256
                or source["calendar_policy"] != CALENDAR):
            raise ValueError("危机合约信息源版本、客户端或日历政策不匹配")
        shared = data.table("crisis_v2_table")
        if type(shared) is not dict:
            raise ValueError("危机合约共享表必须为对象")
        seasons = shared.get("seasonInfoDataMap")
        const = shared.get("constData")
        if type(seasons) is not dict or type(const) is not dict:
            raise ValueError("危机合约共享表缺少赛季或常量")
        self.system_start = _time(const.get("sysStartTime"))
        self.shop_coin_id = _id(const.get("shopCoinId"))
        try:
            data.item(self.shop_coin_id)
        except (KeyError, DomainError) as exc:
            raise ValueError("危机合约商店代币未匹配物品表") from exc
        definitions = {}
        for key, row in seasons.items():
            _id(key)
            if type(row) is not dict or row.get("seasonId") != key:
                raise ValueError("危机合约共享赛季标识不一致")
            start, end = _time(row.get("startTs")), _time(row.get("endTs"))
            if end < start:
                raise ValueError("危机合约共享赛季窗口倒置")
            definitions[key] = SeasonInfo(key, start, end)
        ordered = sorted(definitions.values(), key=lambda r: r.start)
        if any(a.end >= b.start for a, b in zip(ordered, ordered[1:])):
            raise ValueError("危机合约共享赛季窗口重叠，不能选择唯一当前赛季")
        infos = source["seasons"]
        if type(infos) is not dict or not infos:
            raise ValueError("危机合约需要显式导入至少一个赛季信息源")
        rules, payloads, permanent, temporary, refreshes = {}, {}, {}, {}, {}
        for key, entry in infos.items():
            if (key not in definitions or type(entry) is not dict or set(entry) != {"info", "source"}
                    or type(entry["source"]) is not str or not entry["source"]):
                raise ValueError("危机合约信息源缺少共享赛季或来源记录")
            info = entry["info"]
            if type(info) is not dict or set(info) != INFO_FIELDS or info["seasonId"] != key:
                raise ValueError("危机合约信息缓存字段或赛季标识不匹配")
            stages, details = info["mapStageDataMap"], info["mapDetailDataMap"]
            if (type(stages) is not dict or not stages or type(details) is not dict
                    or stages.keys() != details.keys() or type(info["achievementDataMap"]) is not dict
                    or type(info["seasonConst"]) is not dict):
                raise ValueError("危机合约信息地图、成就或赛季常量不完整")
            perm, temp, events = [], [], set()
            for map_id, stage in stages.items():
                _id(map_id)
                if type(stage) is not dict or stage.get("mapId") != map_id:
                    raise ValueError("危机合约地图键不匹配")
                _id(stage.get("stageId"))
                _id(stage.get("levelId"))
                kind = stage.get("stageType")
                if kind == "PERMANENT":
                    perm.append(map_id)
                elif kind == "TEMPORARY":
                    temp.append(map_id)
                else:
                    raise ValueError("危机合约地图类型未匹配当前合同")
                for field in ("startTime", "rewardEndTime"):
                    value = stage.get(field)
                    if value != -1:
                        events.add(_time(value) + int(field == "rewardEndTime"))
                    elif type(value) is not int:
                        raise ValueError("危机合约地图时间非法")
                rules[(key, map_id)] = CrisisV2MapRules(map_id, details[map_id], data_hash=data.manifest["hash"],
                                                      client_elf_sha256=CLIENT_ELF_SHA256)
            if len(perm) != 1:
                raise ValueError("危机合约赛季须匹配唯一永久地图")
            # Preserve the supplied client configuration, including optional
            # field omissions. Do not manufacture showTip or player deltas.
            encoded = json.dumps(info, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
            if len(encoded) > 16 * 1024 * 1024:
                raise ValueError("危机合约单赛季信息源超过接纳上限")
            payloads[key] = encoded
            permanent[key], temporary[key], refreshes[key] = perm[0], tuple(temp), tuple(sorted(events))
        self.seasons = MappingProxyType(definitions)
        self.rules = MappingProxyType(rules)
        self._payloads = MappingProxyType(payloads)
        self.permanent = MappingProxyType(permanent)
        self.temporary = MappingProxyType(temporary)
        self._refreshes = MappingProxyType(refreshes)
        self._challenge_rules = {}
        self._objective_rules = {}
        self.data_hash = data.manifest["hash"]
        self.fingerprint = fingerprint({"policy": POLICY, "data_hash": self.data_hash,
                                        "source": source, "shared": shared})

    def current(self, at: int) -> str:
        _time(at)
        active = [s.season_id for s in self.seasons.values()
                  if at >= self.system_start and s.start <= at <= s.end]
        if not active:
            return ""
        if active[0] not in self._payloads:
            raise DomainError("CRISIS_V2_INFO_MISSING", "当前危机合约赛季尚未导入匹配信息源", 503)
        return active[0]

    def next_refresh(self, at: int) -> int:
        events = {self.system_start, *(v for s in self.seasons.values() for v in (s.start, s.end + 1))}
        current = self.current(at)
        if current:
            events.update(self._refreshes[current])
        return min((v for v in events if v > at), default=0)

    def info(self, season_id: str):
        return json.loads(self._payloads[season_id]) if season_id else None

    def challenges(self, season_id, map_id):
        from terralocal.server.gamedata.crisis_v2_challenges import CrisisV2ChallengeRules

        key = (season_id, map_id)
        if key not in self.rules:
            raise ValueError("危机合约挑战引用了未导入的赛季或地图")
        if key not in self._challenge_rules:
            info = self.info(season_id)
            compiled = CrisisV2ChallengeRules(info["mapDetailDataMap"][map_id], self.rules[key])
            self._challenge_rules.setdefault(key, compiled)
        return self._challenge_rules[key]

    def objectives(self, season_id, map_id):
        from terralocal.server.gamedata.crisis_v2_objectives import CrisisV2ObjectiveRules

        key = (season_id, map_id)
        if key not in self.rules:
            raise ValueError("危机合约任务引用了未导入的赛季或地图")
        if key not in self._objective_rules:
            detail = self.info(season_id)["mapDetailDataMap"][map_id]
            self._objective_rules.setdefault(key, CrisisV2ObjectiveRules(detail, self.rules[key]))
        return self._objective_rules[key]


def validate_crisis_v2(tables, version):
    if SERVER_TABLE not in tables:
        return
    if version is None or "crisis_v2_table" not in tables:
        raise ValueError("危机合约信息源需要同版本共享表和data_version")
    hashes = {name: fingerprint(table) for name, table in tables.items()}
    digest = fingerprint({"adapter": "cn-json-v1", "version": version, "tables": hashes})
    items = tables["item_table"]["items"]
    CrisisV2Catalog(SimpleNamespace(table=tables.__getitem__, item=items.__getitem__,
                                  manifest={"hash": digest, "version": version}))
