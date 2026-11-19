"""Validated, immutable, content-addressed local GameData. No runtime network client."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from functools import cached_property
from pathlib import Path
from typing import Any

from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.conditions import required_stars

REQUIRED = {"character_table", "item_table", "stage_table", "skill_table", "gamedata_const"}
ROOTS = {"item_table": "items", "stage_table": "stages", "zone_table": "zones",
         "mission_table": "missions", "skin_table": "charSkins", "uniequip_table": "equipDict",
         "campaign_table": "campaigns", "roguelike_topic_table": "topics"}
TABLE_NAME = re.compile(r"[a-z][a-z0-9_]{0,95}")
SHA256 = re.compile(r"[0-9a-f]{64}")


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def validate_manifest(manifest: Any) -> dict:
    if not isinstance(manifest, dict) or type(manifest.get("schema")) is not int or manifest["schema"] != 1:
        raise ValueError("GameData manifest schema 非法")
    if manifest.get("adapter") != "cn-json-v1":
        raise ValueError("不支持此 GameData adapter")
    if not isinstance(manifest.get("version"), str) or not 1 <= len(manifest["version"]) <= 1024:
        raise ValueError("GameData version 非法")
    if not isinstance(manifest.get("hash"), str) or not SHA256.fullmatch(manifest["hash"]):
        raise ValueError("GameData 总指纹非法")
    tables, counts = manifest.get("tables"), manifest.get("counts")
    if not isinstance(tables, dict) or not REQUIRED.issubset(tables):
        raise ValueError("GameData 缺少必要表")
    if any(not isinstance(name, str) or not TABLE_NAME.fullmatch(name) or
           not isinstance(value, str) or not SHA256.fullmatch(value) for name, value in tables.items()):
        raise ValueError("GameData 表名称或指纹非法")
    if not isinstance(counts, dict) or counts.keys() != tables.keys() or any(
            type(value) is not int or value < 0 for value in counts.values()):
        raise ValueError("GameData 表计数非法")
    if not isinstance(manifest.get("source"), str) or type(manifest.get("client_verified")) is not bool:
        raise ValueError("GameData 来源或验证标记非法")
    actual = fingerprint({"adapter": manifest["adapter"], "version": manifest["version"], "tables": tables})
    if actual != manifest["hash"]:
        raise ValueError("GameData 总指纹校验失败")
    return manifest


def excel_directory(folder: Path) -> Path:
    for relative in ("excel", "gamedata/excel", "zh_CN/gamedata/excel", "."):
        candidate = folder / relative
        if (candidate / "character_table.json").is_file():
            return candidate.resolve()
    raise ValueError("找不到 character_table.json，请提供解码后的 excel 目录")


def validate_tables(tables: dict[str, Any]) -> dict[str, int]:
    missing = REQUIRED - tables.keys()
    if missing:
        raise ValueError(f"缺少必要表: {', '.join(sorted(missing))}")
    counts = {}
    for name, table in tables.items():
        if not isinstance(table, dict):
            raise ValueError(f"{name} 顶层必须为对象")
        root = ROOTS.get(name)
        entries = table.get(root) if root else table
        if root and not isinstance(entries, dict):
            raise ValueError(f"{name}.{root} 必须为对象")
        counts[name] = len(entries)
    chars, skills = tables["character_table"], tables["skill_table"]
    items, stages = tables["item_table"]["items"], tables["stage_table"]["stages"]
    for char_id, char in chars.items():
        if not char_id.startswith("char_"):
            continue  # Tokens, traps and enemies use a separate client schema.
        if not isinstance(char, dict) or not char.get("phases") or not char.get("rarity"):
            raise ValueError(f"干员结构不完整: {char_id}")
        for skill in char.get("skills", []):
            if skill.get("skillId") and skill["skillId"] not in skills:
                raise ValueError(f"{char_id} 引用不存在的技能 {skill['skillId']}")
        for phase in char["phases"]:
            if not isinstance(phase.get("maxLevel"), int) or phase["maxLevel"] < 1:
                raise ValueError(f"{char_id} maxLevel 非法")
            for cost in phase.get("evolveCost") or []:
                if cost["id"] not in items or cost["count"] < 0:
                    raise ValueError(f"{char_id} 精英材料引用非法")
    for stage_id, stage in stages.items():
        if not isinstance(stage, dict) or stage.get("stageId") != stage_id or not isinstance(stage.get("apCost"), int):
            raise ValueError(f"关卡结构不完整: {stage_id}")
        for field in ("name", "code"):
            if stage.get(field) is not None and not isinstance(stage[field], str):
                raise ValueError(f"{stage_id} 显示字段 {field} 必须为字符串或 null")
        if "slProgress" in stage and (type(stage["slProgress"]) is not int
                                      or not 0 <= stage["slProgress"] <= 2**31 - 1):
            raise ValueError(f"{stage_id} 主线排序值非法")
        for cond in stage.get("unlockCondition") or []:
            if cond["stageId"] not in stages:
                raise ValueError(f"{stage_id} 引用不存在的前置关卡 {cond['stageId']}")
            required_stars(cond.get("completeState", "PASS"))
    const = tables["gamedata_const"]
    for key in ("playerApMap", "playerExpMap", "characterExpMap", "characterUpgradeCostMap", "initCharIdList"):
        if not isinstance(const.get(key), list) or not const[key]:
            raise ValueError(f"gamedata_const.{key} 缺失")
    for char_id in const["initCharIdList"]:
        if char_id not in chars:
            raise ValueError(f"初始干员 {char_id} 缺失")
    if "charword_table" in tables:
        words = tables["charword_table"]
        catalog, languages = words.get("voiceLangDict"), words.get("voiceLangTypeDict")
        if not isinstance(catalog, dict) or not isinstance(languages, dict) or not languages:
            raise ValueError("charword_table 语音目录不完整")
        for word_key, row in catalog.items():
            choices = row.get("dict") if isinstance(row, dict) else None
            if not isinstance(choices, dict) or not choices:
                raise ValueError(f"{word_key} 语音选项不完整")
            for language, definition in choices.items():
                if language not in languages or definition.get("voiceLangType") != language:
                    raise ValueError(f"{word_key} 语音类型引用非法")
        for char_id, char in chars.items():
            if char_id.startswith("char_") and not char.get("isNotObtainable") and char_id not in catalog:
                raise ValueError(f"{char_id} 缺少语音目录")
    if "story_table" in tables:
        stories = tables["story_table"]
        for story_id, story in stories.items():
            if (not isinstance(story, dict) or story.get("id") != story_id or
                    type(story.get("needCommit")) is not bool or type(story.get("disabled")) is not bool or
                    type(story.get("setProgress")) is not int or story["setProgress"] < -1):
                raise ValueError(f"剧情结构不完整: {story_id}")
            condition = story.get("condition") or {}
            for flag in (condition.get("requiredFlags") or []) + (condition.get("excludedFlags") or []):
                if flag not in stories and flag != "init":
                    raise ValueError(f"{story_id} 引用不存在的剧情标记")
            for required in condition.get("requiredStages") or []:
                if required["minState"] not in {"UNLOCKED", "PASS"} or required["maxState"] not in {
                        "UNLOCKED", "PLAYED", "PASS", "COMPLETE"}:
                    raise ValueError(f"{story_id} 关卡状态条件非法")
                if story["needCommit"] and required["stageId"] not in stages:
                    raise ValueError(f"{story_id} 引用不存在的前置关卡")
            for reward in story.get("completedRewards") or []:
                if reward["id"] not in items or type(reward["count"]) is not int or reward["count"] < 0:
                    raise ValueError(f"{story_id} 剧情奖励引用非法")
    if "display_meta_table" in tables:
        home = tables["display_meta_table"].get("homeBackgroundData")
        if not isinstance(home, dict):
            raise ValueError("display_meta_table.homeBackgroundData 缺失")
        for collection, field, default in (("homeBgDataList", "bgId", "defaultBackgroundId"),
                                           ("themeList", "id", "defaultThemeId")):
            rows = home.get(collection)
            if not isinstance(rows, list) or not rows:
                raise ValueError(f"主页 {collection} 目录不完整")
            identifiers = []
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get(field), str) or not 1 <= len(row[field]) <= 96:
                    raise ValueError(f"主页 {collection} 条目非法")
                identifiers.append(row[field])
            if len(set(identifiers)) != len(identifiers) or home.get(default) not in identifiers:
                raise ValueError(f"主页 {collection} 标识重复或默认引用缺失")
    if "gacha_table" in tables:
        from types import SimpleNamespace

        from terralocal.server.gamedata.headhunting import HeadHuntingCatalog
        from terralocal.server.gamedata.recruitment import RecruitCatalog

        source = SimpleNamespace(table=tables.__getitem__, constants=const, characters=chars,
                                 character=chars.__getitem__, item=items.__getitem__, rarity=GameData.rarity)
        try:
            RecruitCatalog(source)
            HeadHuntingCatalog(source)
        except DomainError as exc:
            raise ValueError(exc.message) from exc
    if "campaign_table" in tables:
        from terralocal.server.gamedata.campaigns import validate_campaigns

        validate_campaigns(tables)
    if "roguelike_topic_table" in tables:
        from terralocal.server.gamedata.roguelike import validate_roguelike

        validate_roguelike(tables)
    return counts


def import_data(folder: Path, cache: Path, *, source: str = "user-local") -> dict:
    excel = excel_directory(folder)
    tables = {}
    for path in sorted(excel.glob("*.json")):
        if path.stat().st_size > 128 * 1024 * 1024:
            raise ValueError(f"单表超过 128 MiB: {path.name}")
        tables[path.stem] = json.loads(path.read_text(encoding="utf-8-sig"))
    counts = validate_tables(tables)
    version_file = excel / "data_version.txt"
    version = version_file.read_text("utf-8-sig").strip() if version_file.exists() else "unidentified"
    hashes = {name: fingerprint(table) for name, table in tables.items()}
    digest = fingerprint({"adapter": "cn-json-v1", "version": version, "tables": hashes})
    manifest = {"schema": 1, "adapter": "cn-json-v1", "hash": digest, "version": version,
                "source": source, "counts": counts, "tables": hashes, "client_verified": False}
    validate_manifest(manifest)
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / digest
    if target.exists():
        existing = GameData(target, expected_hash=digest)
        existing.verify()
        return existing.manifest
    temporary = Path(tempfile.mkdtemp(prefix="import-", dir=cache))
    try:
        staged = temporary / digest
        staged.mkdir()
        for name, table in tables.items():
            (staged / f"{name}.json").write_bytes(canonical(table))
        (staged / "manifest.json").write_bytes(canonical(manifest))
        GameData(staged, expected_hash=digest).verify()
        os.replace(staged, target)
    finally:
        if temporary.exists():
            if temporary.is_symlink() or temporary.is_junction() or temporary.resolve().parent != cache.resolve():
                raise ValueError("GameData 临时目录超出缓存范围")
            shutil.rmtree(temporary)
    return manifest


class GameData:
    def __init__(self, directory: Path, *, expected_hash: str | None = None):
        self.requested_directory = directory
        self.directory = directory.resolve()
        self.expected_hash = expected_hash
        self.manifest = self._read_manifest()
        self._tables: dict[str, dict] = {}

    def _read_manifest(self) -> dict:
        try:
            manifest = validate_manifest(json.loads((self.directory / "manifest.json").read_bytes()))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("GameData manifest 无法读取") from exc
        if self.expected_hash is not None and manifest["hash"] != self.expected_hash:
            raise ValueError("GameData 配置指纹不匹配")
        if self.requested_directory.name != manifest["hash"] or self.directory.name != manifest["hash"]:
            raise ValueError("GameData 缓存目录指纹不匹配")
        return manifest

    def verify(self) -> None:
        manifest = self._read_manifest()
        tables, hashes = {}, {}
        for name, expected in manifest["tables"].items():
            # Explicit verification always reads disk; cached tables cannot
            # hide a file changed since a previous successful verification.
            try:
                path = self.directory / f"{name}.json"
                if path.stat().st_size > 128 * 1024 * 1024:
                    raise ValueError(f"GameData 单表超过 128 MiB: {name}")
                tables[name] = json.loads(path.read_bytes())
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"GameData 表无法读取: {name}") from exc
            hashes[name] = fingerprint(tables[name])
            if hashes[name] != expected:
                raise ValueError(f"GameData 校验失败: {name}")
        actual = fingerprint({"adapter": manifest["adapter"], "version": manifest["version"], "tables": hashes})
        if actual != manifest["hash"]:
            raise ValueError("GameData 总指纹校验失败")
        try:
            counts = validate_tables(tables)
        except (KeyError, TypeError, AttributeError, DomainError) as exc:
            raise ValueError("GameData 表结构校验失败") from exc
        if counts != manifest["counts"]:
            raise ValueError("GameData 表计数校验失败")
        self.manifest = manifest
        self._tables.update(tables)

    def table(self, name: str) -> dict:
        if name not in self.manifest["tables"]:
            raise DomainError("GAMEDATA_MISSING", f"当前数据缺少 {name}", 503)
        if name not in self._tables:
            self._tables[name] = json.loads((self.directory / f"{name}.json").read_bytes())
        return self._tables[name]

    @cached_property
    def characters(self) -> dict:
        return self.table("character_table")

    @cached_property
    def items(self) -> dict:
        return self.table("item_table")["items"]

    @cached_property
    def stages(self) -> dict:
        return self.table("stage_table")["stages"]

    @cached_property
    def mainline_progress_order(self) -> tuple[str, ...]:
        # The frozen chapter selector chooses the smallest nonzero slProgress
        # among unlocked, unpassed stage views. Alternate difficulty projection
        # remains separate; this catalog covers the normal mainline contract.
        ordered = []
        indexes = set()
        for stage_id, stage in self.stages.items():
            index = stage.get("slProgress", 0)
            if (stage.get("stageType") != "MAIN" or stage.get("difficulty") != "NORMAL"
                    or stage.get("diffGroup") not in ("NONE", "NORMAL") or index == 0):
                continue
            if type(index) is not int or not 0 < index <= 2**31 - 1 or index in indexes:
                raise DomainError("GAMEDATA_INVALID", "主线排序值非法或重复", 503)
            indexes.add(index)
            ordered.append((index, stage_id))
        return tuple(stage_id for _, stage_id in sorted(ordered))

    @cached_property
    def constants(self) -> dict:
        return self.table("gamedata_const")

    def character(self, char_id: str) -> dict:
        if char_id not in self.characters or not char_id.startswith("char_"):
            raise DomainError("UNKNOWN_OPERATOR", "干员不存在")
        return self.characters[char_id]

    def stage(self, stage_id: str) -> dict:
        if stage_id not in self.stages:
            raise DomainError("UNKNOWN_STAGE", "关卡不存在")
        return self.stages[stage_id]

    def item(self, item_id: str) -> dict:
        if not isinstance(item_id, str) or not 1 <= len(item_id) <= 96 or item_id.strip() != item_id:
            raise DomainError("INVALID_ITEM_ID", "物品标识无效")
        if item_id not in self.items:
            if item_id in self.furnitures:
                furniture = self.furnitures[item_id]
                return {"itemId": item_id, "itemType": "FURN", "name": furniture["name"],
                        "rarity": furniture["rarity"]}
            if item_id.startswith("char_") and item_id in self.characters:
                return {"itemId": item_id, "itemType": "CHAR", "name": self.characters[item_id]["name"]}
            if ("skin_table" in self.manifest["tables"]
                    and item_id in self.table("skin_table").get("charSkins", {})):
                from terralocal.server.domain.skins import definition

                return definition(self, item_id)
            raise DomainError("UNKNOWN_ITEM", f"物品不存在: {item_id}")
        return self.items[item_id]

    @cached_property
    def furnitures(self) -> dict:
        return (self.table("building_data").get("customData", {}).get("furnitures", {})
                if "building_data" in self.manifest["tables"] else {})

    @cached_property
    def recruitment(self):
        from terralocal.server.gamedata.recruitment import RecruitCatalog

        return RecruitCatalog(self)

    @cached_property
    def campaigns(self):
        from terralocal.server.gamedata.campaigns import CampaignCatalog

        if "campaign_table" not in self.manifest["tables"]:
            raise DomainError("CAMPAIGN_DATA_MISSING", "缺少匹配的剿灭静态表", 503)
        return CampaignCatalog(self.table("campaign_table"), self.stages, lambda item_id: self.item(item_id)["itemType"])

    @cached_property
    def rogue_topics(self):
        from terralocal.server.gamedata.roguelike import RogueTopicCatalog

        if "roguelike_topic_table" not in self.manifest["tables"]:
            raise DomainError("ROGUE_DATA_MISSING", "缺少匹配的现代集成战略主题表", 503)
        return RogueTopicCatalog(self.table("roguelike_topic_table"))

    @cached_property
    def rogue_initial(self):
        from terralocal.server.gamedata.rogue_initial import FirstThemeInitialRules

        return FirstThemeInitialRules(self)

    @cached_property
    def rogue_recruit(self):
        from terralocal.server.gamedata.rogue_recruit import FirstThemeRecruitRules

        return FirstThemeRecruitRules(self)

    @cached_property
    def rogue_upgrades(self):
        from terralocal.server.gamedata.rogue_upgrades import FirstThemeUpgradeRules

        return FirstThemeUpgradeRules(self)

    @cached_property
    def rogue_special_recruit(self):
        from terralocal.server.gamedata.rogue_special_recruit import FirstThemeSpecialRecruitRules

        return FirstThemeSpecialRecruitRules(self)

    @cached_property
    def rogue_recruit_costs(self):
        from terralocal.server.gamedata.rogue_recruit_costs import FirstThemeRecruitCostRules

        return FirstThemeRecruitCostRules(self)

    @cached_property
    def rogue_battle_attributes(self):
        from terralocal.server.gamedata.rogue_battle_attributes import FirstThemeBattleAttributes

        return FirstThemeBattleAttributes(self)

    @cached_property
    def rogue_global_buffs(self):
        from terralocal.server.gamedata.rogue_global_buffs import FirstThemeGlobalBuffs

        return FirstThemeGlobalBuffs(self)

    @cached_property
    def rogue_capacity_relics(self):
        from terralocal.server.gamedata.rogue_capacity_relics import FirstThemeCapacityRelics

        return FirstThemeCapacityRelics(self)

    @cached_property
    def rogue_gold_relics(self):
        from terralocal.server.gamedata.rogue_gold_relics import FirstThemeGoldRelics

        return FirstThemeGoldRelics(self)

    @cached_property
    def rogue_currency_relics(self):
        from terralocal.server.gamedata.rogue_currency_relics import FirstThemeCurrencyRelics

        return FirstThemeCurrencyRelics(self)

    @cached_property
    def rogue_life_relics(self):
        from terralocal.server.gamedata.rogue_life_relics import FirstThemeLifeRelics

        return FirstThemeLifeRelics(self)

    @cached_property
    def rogue_resource_relics(self):
        from terralocal.server.gamedata.rogue_resource_relics import FirstThemeResourceRelics

        return FirstThemeResourceRelics(self)

    @cached_property
    def rogue_merchant_relics(self):
        from terralocal.server.gamedata.rogue_merchant_relics import FirstThemeMerchantRelics

        return FirstThemeMerchantRelics(self)

    @cached_property
    def rogue_base_relics(self):
        from terralocal.server.gamedata.rogue_base_relics import FirstThemeBaseRelics

        return FirstThemeBaseRelics(self)

    @cached_property
    def rogue_support_tools(self):
        from terralocal.server.gamedata.rogue_support_tools import FirstThemeSupportTools

        return FirstThemeSupportTools(self)

    @cached_property
    def rogue_tool_effects(self):
        from terralocal.server.gamedata.rogue_tool_effects import FirstThemeToolEffects

        return FirstThemeToolEffects(self)

    @cached_property
    def rogue_bank(self):
        from terralocal.server.gamedata.rogue_bank import FirstThemeBankRules

        return FirstThemeBankRules(self)

    @cached_property
    def rogue_bank_items(self):
        from terralocal.server.gamedata.rogue_bank_items import FirstThemeBankItems

        return FirstThemeBankItems(self)

    @cached_property
    def rogue_relic_archive(self):
        from terralocal.server.gamedata.rogue_collection import FirstThemeRelicArchive

        return FirstThemeRelicArchive(self)

    @cached_property
    def rogue_roster_unlocks(self):
        from terralocal.server.gamedata.rogue_roster_unlocks import FirstThemeRosterUnlocks

        return FirstThemeRosterUnlocks(self)

    @cached_property
    def rogue_capacity_unlocks(self):
        from terralocal.server.gamedata.rogue_capacity_unlocks import FirstThemeCapacityUnlocks

        return FirstThemeCapacityUnlocks(self)

    @cached_property
    def rogue_floor_unlocks(self):
        from terralocal.server.gamedata.rogue_floor_unlocks import FirstThemeFloorUnlocks

        return FirstThemeFloorUnlocks(self)

    @cached_property
    def rogue_ending_unlocks(self):
        from terralocal.server.gamedata.rogue_ending_unlocks import FirstThemeEndingUnlocks

        return FirstThemeEndingUnlocks(self)

    @cached_property
    def rogue_ending_variants(self):
        from terralocal.server.gamedata.rogue_ending_variants import FirstThemeEndingVariants

        return FirstThemeEndingVariants(self)

    @cached_property
    def rogue_deployment_goals(self):
        from terralocal.server.gamedata.rogue_deployment_goals import FirstThemeDeploymentGoals

        return FirstThemeDeploymentGoals(self)

    @cached_property
    def rogue_endings(self):
        from terralocal.server.gamedata.rogue_endings import FirstThemeEndings

        return FirstThemeEndings(self)

    @cached_property
    def rogue_map(self):
        from terralocal.server.gamedata.rogue_map import FirstThemeMapCatalog

        return FirstThemeMapCatalog(self)

    @cached_property
    def rogue_levels(self):
        from terralocal.server.gamedata.rogue_levels import FirstThemeLevelCurve

        self.rogue_topics.topic("rogue_1")
        return FirstThemeLevelCurve(self.table("roguelike_topic_table")["details"]["rogue_1"]
                                   ["detailConst"]["playerLevelTable"])

    @cached_property
    def rogue_scenes(self):
        from terralocal.server.gamedata.rogue_events import FirstThemeSceneCatalog

        return FirstThemeSceneCatalog(self)

    @cached_property
    def rogue_fixed_events(self):
        from terralocal.server.gamedata.rogue_events import fixed_programs

        return fixed_programs(self.rogue_scenes)

    @cached_property
    def rogue_trade_events(self):
        from terralocal.server.gamedata.rogue_events import trade_programs

        return trade_programs(self.rogue_scenes)

    @cached_property
    def rogue_health_trade_events(self):
        from terralocal.server.gamedata.rogue_events import health_trade_programs

        return health_trade_programs(self.rogue_scenes)

    @cached_property
    def rogue_dance_events(self):
        from terralocal.server.gamedata.rogue_dance import programs

        return programs(self.rogue_scenes)

    @cached_property
    def rogue_ticket_events(self):
        from terralocal.server.gamedata.rogue_ticket_events import programs

        return programs(self)

    @cached_property
    def rogue_recruit_events(self):
        from terralocal.server.gamedata.rogue_recruit_events import programs

        return programs(self)

    @cached_property
    def rogue_relic_events(self):
        from terralocal.server.gamedata.rogue_relic_events import programs

        return programs(self)

    @cached_property
    def rogue_rest_events(self):
        from terralocal.server.gamedata.rogue_rest import programs

        return programs(self)

    @cached_property
    def headhunting(self):
        from terralocal.server.gamedata.headhunting import HeadHuntingCatalog

        return HeadHuntingCatalog(self)

    @staticmethod
    def rarity(char: dict) -> int:
        value = char["rarity"]
        return int(value.removeprefix("TIER_")) - 1 if isinstance(value, str) else int(value)


def diff_data(left: GameData, right: GameData) -> dict:
    left.verify()
    right.verify()
    result = {}
    for name in sorted(left.manifest["tables"].keys() | right.manifest["tables"].keys()):
        a = left.table(name) if name in left.manifest["tables"] else {}
        b = right.table(name) if name in right.manifest["tables"] else {}
        root = ROOTS.get(name)
        x, y = a.get(root, {}) if root else a, b.get(root, {}) if root else b
        result[name] = {"added": sorted(y.keys() - x.keys()), "removed": sorted(x.keys() - y.keys()),
                        "changed": [k for k in x.keys() & y.keys() if x[k] != y[k]],
                        "schema_changed": sorted(a.keys()) != sorted(b.keys()) if root else False}
    return result
