# TerraLocal：危机合约隔离启动与本地宝藏领奖（2026-11-25）

## 基线与本轮结论

继续在 `codex/development` 的现有未提交工作区开发，HEAD 基线仍为 `99e573d`。接手前的启动器、独立历史配置与上一批存档准入修复均保留。没有重打关卡，没有启动模拟器、使用现用存档、对外发请求、创建新发行物、提交 Git 或推送远程。此前接手细节见 [开发交接](terralocal-dev-handoff-2026-11-25.md)。

## 隔离生命周期验收

`tools/verify_crisis_v2_save.py` 只接受本项目 `.cache` 下的匹配数据目录（14457902 开头）和一个不存在的 `.cache` 子目录。脚本复制静态数据，不复制原有账号、证书、绑定文件或 SQLite；使用 `emulator_index=None` 和 127.0.0.1，重建自己的 CA 与端口。不更改原冻结数据。通过打包前实际使用的 `ServerGroup` 启动真实监听器，以本地 CA 验证 HTTPS，做新账号登录和完整同步。测试时钟固定在历史首季，不能据此说现时开放。

首次验收：新库首开、冷重启、CLI `backup` 和 `restore --output` 后新目录再次启动；三次均核到首季一张永久和四张临时地图，Crisis V2 同步子树相同。共 9 次生命周期 HTTPS 成功、3 个服务组有序停机。运行入口使用同一个 Python 验证进程，不能描述成 3 个独立进程。证据 `.cache/dot-crisis-smoke-20261125-115817-862/verification.json`。

## 本地领奖实现与限制

- 本地接口 `POST /local/v1/crisis-v2/claim-treasure`，提交 `seasonId`、`mapId`、`slotId`；持同一账号本地会话且必须传 `idempotency-key`。只处理当前有效赛季的永久地图宝藏任务，同时检查地图的本地开始/结束窗口。奖励和数量从绑定的数据版本取得，客户端不能提交奖励内容。
- `terralocal/server/domain/crisis_v2_claims.py` 检查进度状态、最低达成条件和地图确有通关。当前支持单件可授予服装、单件家具及单份纯材料包。服装和家具沿用现有库存逻辑；材料包读取同版本 `item_table.itemPackInfos` 的完整平坦 `MATERIAL` 清单，不发可复用的包本体。缺表、重复项、非法数量、错误物品类型或嵌套内容拒绝，不会部分发奖。这是本地展开策略，不声明已确认官方领取语义。
- 发奖、状态从 1 改为 2、增量及账号级首次回执在同一 SQLite 事务内提交。同账号同键同请求在重登、重启及恢复后仍返回原答复；改键后已领返回冲突，旧战斗回执不会二次发奖。新增本地路由，不更改任何原版领奖路由或结算契约；没有数据库迁移。

## 验证记录

1. 初版合成 5 项通过，随后新增服装和关季，连相邻回归共 108 项通过。材料包实现后重跑受影响用例 25 项通过（本地领奖 9 项、任务事务和准入 16 项）；这些结果有交集，不相加。Ruff、`git diff --check` 通过。涵盖未完成、错误地图和未登录、错误物品类型、未知奖励、坏进度、并发仅发一次、故障回滚、真实 SQLite 备份恢复和跨登录回执、材料包重复成员全事务拒绝。
2. 用实际冻结 GameData 只读核对：服装从 `skin_table`、家具从 `building_data` 解析；材料包及其 3 种材料从 `item_table` 解析。仅检查原始 `items` 字典会错判前两者缺失，最终以 `GameData.item()` 回读为准。第一次真实领奖验证两类 200、尚未实现的材料包预期 501；保留 `.cache/dot-crisis-reward-https-20261125-120117-145/verification.json`。
3. 最终冻结测试 3 类均 200，再次同键获相同回执，最终同步均显示已领；材料包输出逐项与冻结清单吻合。同次生命周期 HTTPS 9 成功；额外领奖档 8 个成功请求（登录、三次领取、三次重试、一次同步），共 4 次服务组正常停机；整条命令退出 0。领奖档的完成资格是测试预置，不算真实客户端打关，更不代表当前赛季或官方功能已恢复。最终证据 `.cache/dot-crisis-pack-20261125-120207-139/https/verification.json` 和 `.cache/dot-crisis-pack-20261125-120207-139/junit.xml`。

```powershell
Set-Location 'D:\CODE\VibeCoding\test\TerraLocal'
. .\tools\env.ps1
$src = Get-ChildItem -LiteralPath '.cache/crisis-20261119/native-battles-https-v2/data/cache' -Directory | Select-Object -First 1
$dst = '.cache/crisis-local-claim-proof-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff')
.\.venv\Scripts\python.exe -m tools.verify_crisis_v2_save $src.FullName $dst --exercise-rewards
$env:PYTEST_ADDOPTS = ''
$unit = Join-Path $PWD.Path ($dst + '-tests')
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp $unit tests/test_crisis_v2_claims.py tests/test_crisis_v2_objective_transactions.py tests/test_crisis_v2_save_admission.py
```

## 下一步

先核额外符文解锁所需的资格、条件及持久化字段，保持地图类型和历史窗口的隔离；商店及原始回放各自单独验证。原版客户端领奖与画面、新 Windows 包、整机断网、两小时实机稳定性和 HarmonyOS 未完成。下一位接手先比对 `git status`，未提交差异中本批源码是 `domain/crisis_v2_claims.py`、`protocol/crisis_v2.py`、`tests/test_crisis_v2_claims.py` 和 `tools/verify_crisis_v2_save.py`。本批没有新公开或恢复检查点。