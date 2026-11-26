# 危机合约 V2：额外符文、本地商店和战报归档（2026-11-25）

## 范围与完成情况

2026-11-26 修订：原版导览和冻结首季四临时图反例否定“只通关一次就可解锁”的宽松本地条件。新授予要求完成关联图全部已核任务，空定义拒绝；旧授予/回执保持。此前六项预置资格检查仅代表旧本地策略，不证明原版规则一致。[修复与真实冻结检查](crisis-native-client-2026-11-26.md#原版反例轮换任务与符文提前解锁)

- 额外符文：`POST /local/v1/crisis-v2/unlock-rune`，`seasonId`、永久地图 `mapId`、`slotId`，需 `idempotency-key`。本地授权要求同一账号通关 `mapAttachOn` 指向的临时地图，且到达 `startTs`、赛季开放；写入 `exRunes=2` 并由既有选槽逻辑消费。未知映射、普通节点、错误账号和已关闭赛季拒绝。使用冻结数据作为关联和时间依据，不把本地发放条件冒称官服。
- 商店：仅显式提供 `crisis_v2_local_shop.json` 才启用。读目录 `GET /local/v1/crisis-v2/shop`；`POST .../shop/claim-credit` 提交 `mapId`，`POST .../shop/buy` 提交 `offerId`，均需 `idempotency-key`。购买事务原子更新余额、限库存和发奖；通关代币按地图只领一次。保存和备份与该目录指纹绑定，拒绝换目录、余额或库存记录损坏。旧库没有商店账本时不提前查询不存在的危机合约表。没有配置时无默认价格、库存或资金。
- 战报：`GET /local/v1/crisis-v2/history?limit=20&offset=0` 与 `/history/{battleId}`，仅本人、已结束的记录，分页确定且只读，返回赛季、地图、结果、分数、评语等安全字段，不返回登录凭据或原始日志。
- 原始日志：`settings.json` 的 `crisis_archive_replays` 默认 `false`，未改现用设置。显式开启时，首次已验证通关可在单一事务归档原始 BattleLog，按账号限 20 条、每条至多 1,000,000 字符；超限不阻止通关，不自动淘汰。`GET .../history/{battleId}/journal` 仅同账号可读且 `Cache-Control: no-store`；校验所有权、战斗终态、首个日志摘要。归档数据可能含私人局内数据，随本地 SQLite 备份，绝不随源码发布。原始载荷可读不等于原版能播放，不回填旧战斗。

## 本地商店目录格式

设置放在所选隔离数据目录，必须匹配 GameData SHA-256、已导入赛季、确有其物的物品 ID。以下键名是本地 API，数字只是示例，非官服：

```json
{
  "schemaVersion": 1,
  "gameDataHash": "<当前 GameData 的 64 位 SHA-256>",
  "seasonId": "<已导入的赛季 ID>",
  "credits": {"<同赛季地图 ID>": 7},
  "offers": [{"id": "local-demo", "price": 3, "stock": 1, "itemId": "<物品 ID>", "itemType": "FURN"}]
}
```

当前匹配目录带 6 个 `dailyRuneUnlcokDataMap` 入口、首季五图和商店代币；两个宝藏记录有商品 ID，但核对同版本 `shop_client_table` 后没有相应的危机合约商品、价格和库存清单。首季 `achievementDataMap` 为空，不据此推定其他版本没有成就。未补造官网目录、成就、自然投放规则或助战。

## 回归与证据

- 危机合约服务端、启动诊断和备份广测 382 通过、2 个旧客户端绑定用例未跑（另排除数据准备工具测试）；Ruff 与空白检查通过。旧库场景先复现缺 `crisis_v2_accounts` 报错，然后补账本存在性门槛，36 个影响用例复验通过。两组有重叠，不能相加。
- 冻结首季使用实际 ServerGroup、回环 HTTPS、本地 CA 和隔离测试账号：6 个符文解锁、同步可见、定制商店领代币/买家具/重复不二扣、库存为零、战报空列表，服务正常停止。临时图通关标记是预置测试条件，价格/额度是自有 QA 目录，不是官服验收。
- 本地可重复测试：加载 `tools/env.ps1`，给 pytest 指定项目内唯一 `--basetemp`，运行 `tests/test_crisis_v2_unlocks.py`、`tests/test_crisis_v2_shop.py`、`tests/test_crisis_v2_history.py`、`tests/test_crisis_v2_journals.py`，并按影响重跑 `tests/test_crisis_v2_native_battles.py`、`tests/test_backup_recovery.py`、`tests/test_doctor.py`。原始数据、测试 SQL、运行日志和已验证原始日志不上传。

## 未完成与下一步

这里完成的是兼容服务的本地功能和隔离环境验收，不是假定原版适配完成。仍要从可核实的接口资料或自有离线兼容试验确认：原版入口到战斗/领奖/符文/商店的逐项走通，以及原版回放消费；真实商店目录、其余赛季、助战、成就、卫戍协议及其他模式未纳入本批的完成范围。原版界面由客户端提供，不另做仿制。新 Windows 包和整机断网尚未验收。
