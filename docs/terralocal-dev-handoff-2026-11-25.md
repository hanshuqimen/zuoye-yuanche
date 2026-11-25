# TerraLocal 开发交接：危机合约 V2 测试档准入（2026-11-25）

## 接手基线与现有改动

- 项目目录：`D:\CODE\VibeCoding\test\TerraLocal`，分支 `codex/development`，本批接手时 HEAD `99e573d`。代码实现基线 `ec9f1a6`，账本记录其公开检查点为 `e1157d6`；本轮未重新核对远端。接手对象以实际工作区为准，不以旧账本替代未提交代码。
- 接手时已有 6 个跟踪文件修改：`terralocal/launcher/android.py`、`terralocal/launcher/client_binding.py`、`terralocal/server/compatibility/profile.py`、`terralocal/server/domain/crisis_v2.py`、`terralocal/server/services/runtime.py`、`tests/test_launcher_android.py`；另有未跟踪的 `tests/test_crisis_v2_client_profile.py`。不要回滚、清理、格式化这些现有差异或误标为本轮新增。
- 已有工作新增 `cn-android-2.7.71-crisis-qa`，限制匹配历史危机合约数据指纹，将协议版本映射至现有展示协议；启动前以只读方式检查旧账号是否已绑定危机合约。启动器和客户端部分未在本轮修改或运行。

## 这批实际修改

1. `terralocal/server/domain/crisis_v2.py:preflight`：独立测试配置遇到已存在危机合约表、但缺少基础 `accounts` 表的损坏库时，归类为存档表不完整，给出保留原档并从已验证备份恢复的诊断。修复前只读 SQL 去查缺失表并抛出 `sqlite3.OperationalError`，虽然已中止启动，但没有项目可识别的诊断。
2. 将独立配置的未绑定检查归并。旧库无危机合约表时，只要已有账号就拒绝；有危机合约表时，用 `NOT EXISTS` 检查是否存在未绑定账号。缺失文件、全空文件、无账号旧表及正确绑定状态没有因此被拒绝。普通配置的旧库迁移行为不变，未新增数据库表、迁移或协议字段。
3. 新增 `tests/test_crisis_v2_save_admission.py`：缺基础表准确报错、空旧库接受、已有账号旧库拒绝且普通配置仍允许旧版路径。对隔离 SQLite 文件比对预检前后字节。现有 `test_crisis_v2_client_profile.py` 未修改。

## 实际验证和可重跑命令

- 接手基线：6 条现有服务端准入用例通过，2 条启动器客户端绑定用例未运行。
- 先加回归，再修实现。修复前 1 失败、2 通过：缺基础表为 `sqlite3.OperationalError: no such table: accounts`；保留目录 `.cache/dot-admission-before-20261125-114809-672`。
- 修复后第一组 76 通过、2 条启动器绑定用例未运行；第二组 141 通过。两组测试文件不重叠，合计 217 通过。只有已知 Starlette/httpx 弃用警告；相邻战斗测试使用自有合成夹具，这是服务端接口/事务检查，不是原生客户端验收。
- 两组 JUnit：`.cache/dot-admission-after-20261125-114832-675/junit.xml`、`.cache/dot-crisis-regression-20261125-114913-752/junit.xml`。Ruff 对本轮两个源码/测试文件及 `git diff --check` 均通过。没有运行全仓测试。

```powershell
Set-Location 'D:\CODE\VibeCoding\test\TerraLocal'
. .\tools\env.ps1
$env:PYTEST_ADDOPTS = ''
$qa = Join-Path $PWD.Path ('.cache\crisis-handoff-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
New-Item -ItemType Directory -Path $qa | Out-Null
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp "$qa\save" --junitxml "$qa\save.xml" tests/test_crisis_v2_save_admission.py tests/test_crisis_v2_client_profile.py tests/test_crisis_v2_information.py tests/test_crisis_v2_persistence.py tests/test_backup_recovery.py tests/test_doctor.py -k 'not binding_requires_existing_sdk3_adapter'
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp "$qa\battle" --junitxml "$qa\battle.xml" tests/test_crisis_v2_battle_sessions.py tests/test_crisis_v2_clears.py tests/test_crisis_v2_exits.py tests/test_crisis_v2_native_battles.py tests/test_crisis_v2_objective_transactions.py
.\.venv\Scripts\python.exe -m ruff check --no-cache terralocal/server/domain/crisis_v2.py tests/test_crisis_v2_save_admission.py
git --no-optional-locks diff --check
```

本轮所有新增文件均在项目目录内；没有打开其现用存档、启动/操作模拟器、重新打包 Windows 发行物、提交 Git 或推送公开仓库。以隔离数据库、文件级检查和 JUnit 为证，不能据此声称已通过原生画面、旧启动器或发行物验收。

## 下一位接手者：按这个顺序推进

1. 先读 `docs/project-ledger/README.md`、`REQUIREMENTS.md`、`STATE.md`；用 `git --no-optional-locks status --short --branch` 对照上列接手边界。在具备工作区读取权限的终端运行；只读沙箱曾返回 `this operation must be run in a work tree`，实际确认不是 Git 仓库丢失。不要 reset、clean 或替换现有未提交差异。
2. 用新建、隔离的自有数据确认端到端启动：`StartupInputs` 是启动、诊断和暂存恢复共享的校验入口（见 `terralocal/server/services/runtime.py`、`doctor.py`、`backups.py`）。优先补真实配置通过的正例，以及新库创建账号后重启、错数据拒绝、旧档备份恢复不转换的组合；仅使用允许的副本/夹具，不切换现用设置。单元测试行数不能替代启动验证。
3. 现阶段设计从 `terralocal/server/domain/crisis_v2_clears.py` 的通关投影和可重放终态出发。`crisis_v2_objectives.project/apply` 写进度及“可领取”状态而不发奖；`crisis_v2_state.py` 定义展示字段，`domain/crisis_v2.py` 负责账号到地图的投影。新增领取时应在同一事务内核账号、已确认的赛季/地图和条件，持久化首次收据和发放记录，覆盖重复请求同一结果、并发仅发一次、写入异常整体回滚、重启及备份恢复。不要在旧结算回放里重新发奖。奖励 ID、奖励量、领取时间窗或响应未有可靠依据时，不开放猜测出来的接口，先用明确标注的本地合成协议做验证。
4. 解锁、商店、原始回放分别立项；不能用结算成功代替奖励领取，也不要用 HTTP 200 代替游戏画面消费。实测支持范围、隔离副本规则与验收证据见 [原生路由报告](crisis-native-battles-2026-11-21.md)。原始客户端画面、任务领取/解锁/商店、原始回放、新 Windows 包、整机断网、两小时实机稳定性及 HarmonyOS 继续未完成。仅在合法、自有且隔离的环境中测试；不要触碰官方账号认证、绕过受保护服务或使用现用游戏存档。
5. 后续合并时先区分上一轮未提交内容与本批 `preflight` 局部修改；复审测试和数据排除后再建立源码检查点。公开提交与实际恢复回读要分别记录；本轮没有新检查点。
## 同日后续开发
此页保留首次接手事实，顺序中的启动、重启、备份恢复与本地宝藏领奖已按 [2026-11-25 后续记录](crisis-local-claims-2026-11-25.md) 推进；后续以账本 STATE 顶部和该报告为准。