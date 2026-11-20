# 危机合约 V2：结算日志、原生状态与会话绑定

本阶段在[0039 会话](crisis-battle-sessions-2026-11-20.md)上接入结算解码和只读绑定。结果分类、计数解释、进度、奖励及原生结算路由尚未接通；解析成功不等于通关或发奖。

## 新的客户端依据

两次 REA/Ghidra 会话实际分析 15 个默认方法，共 9,712 字节：第一批 8 方法/6,040 字节来自冻结 APK，第二批 7 方法/3,672 字节来自有界加载代码和一个冻结文件方法。两会话 public status/close 成功，控制器及子进程退出 0，输入指纹保持。第二批使用不同捕获来源，但每个方法的完整范围只取一个来源，不冒称同一进程快照。

第一批容器 SHA-256 `996c63d48847ad18e1eeeecee4381e5c9178bb18e47adea09ad10559e6a5e6ed`，第二批 `1c6b9161d2fd1d35f1dec2693a1a46df36fd40e39c43257eb165b65e72153413`。原始代码页、伪代码及第三方工具只保存在本地。

关键对应：

- M101836 `_AchieveBattleLog` 正常路径取得 BattleController 的 Journal，调用 `CreateBattleLog(journal, battleLogMeta:null)`，再调用 `CompressBattleLog`。结合已有原生 ZIP 验证，可复用既有 UTF-8 JSON/单 ZIP 条目/Base64 解析；这不使危机合约支持代理作战。本方法元数据声明 string，REA 因未知被调函数返回原型显示 void；采用实际正常指令调用链和声明，不把伪代码返回类型当作新协议。
- M163053 `UpdatePlayerData` 在普通 `rune` 或永久地图 `exRunes` 词典读到值 3 时写入 `m_isCompleted`，M163044 读取同一偏移 0x48。额外符文值 0 保持 unknown；值 1 为已知但不连通，值至少 2 连通。这补充核实既有地图规则，不根据未核原始枚举载荷推广其他枚举。
- M163234 的符文组 `isComplete` 判断保存状态大于 0。M162604 在任务状态为 1 时标记有待领取奖励，为 2 时视为已领取；缺条目且配置仍有任务会使 allGet 为 false，空容器不自动证明所有任务完成。
- M163253 `_RefreshMissionItem` 的任务类型 0 查 runePack、1 查 challenge、2 查 reward；对应 MissionItemModel.missionInfo、CrisisV2MissionInfo.id/type 和三个已声明词典参数。M163254 把状态 1 排在可领取位置、2 排在已领位置。具体状态、奖励和请求交易仍需接入，不能把 UI 消费者当作官方后端算法。

`_OnUnitBorn`、`_OnEnemyReachedExit`、`_OnGameOver` 确认评论管理器经 BattleLogger.LogExtraBattleInfo 写入事件/属性数据。静态文件中的元数据用法指针和有界字面量表分别对应三个格式：`{0},{1},{2}`、`{0},{1},{2},{3}`、`{0},{1},{2},{3:F3}`。类型绑定为 LogExtraBattleInfo.LogType 和 LogAttributeType；正常调用路径分别读取单位 cost、漏怪 hpRatio 和战斗剩余 cost。这些是客户端日志来源依据，还没有实现全部评论判定。

用已核 M27994 的 `crisisV2/battleStart` 字面量作阳性对照后才接纳本版本索引解释。首次对照错误地只尝试未保护定义，已保留失败并改为逐项边界及预期文本核对；不使用“所有元数据统一 XOR”的规则，也不读取活动堆字符串或认证。

分析边界：两个单位事件方法的异常路径伪代码包含邻接方法，原因是未知 throw helper 返回性；仅采用原方法范围内正常路径。旧 `_UpdateHighestScoreList` 只复制服务端 scoreTotal，不能据此发明官方累计/最高分更新算法。活动 Hotfix 未读取。

## 受控读取及失败现场

第一次 index1 启动在 APK SHA-256 校验触发 8 秒超时，尚未读取代码；正常收尾关闭 index1，index0 和现用保存保持。该失败目录 `loaded-progress-log-20261120-v5/` 保留。

新目录 v6 沿用全部硬件/APK/ELF/资源/f441 数据/TLS/离线校验，只读预先列出的 0x3120000、0x413f000、0x4140000 三页，共 12,288 字节。每次 Android 命令仍限 8 秒；控制器为只读哈希增加最多三次重试，本次成功尝试实际没有发生哈希重试。读取前同一 shell 核硬件和游戏进程，不读取玩家、认证或活动 Hotfix 对象。没有游戏 API 监听器或客体 dump 文件，最终 index1 停止，index0/现用设置及保存指纹保持。没有新关卡游玩。

## 源码行为

新增 `CrisisFinishRequest`、`DecodedCrisisFinish` 和 `CrisisSubmission`，沿用 CommonFinishBattleRequest 的加密基类并保留原始 rank、interrupt、giveUp。此处不解释星数或是否通关。额外 battleLog 单独解析，缺失/null/空值保留为显式 None，不能凭解析通过发奖。非空日志损坏或与结算关卡冲突时拒绝，不回显日志内容。

危机合约日志采用明确的本地 6 MiB 接纳上限，为默认 8 MiB HTTP 请求中的基类数据留空间；它不是官方协议最大值。复用 ZIP 解码的有界参数，普通代理入口仍保持原先 1,000,000 字符上限，解压 JSON 仍最多 16 MiB。只在内存读取单条目，不落地解压；重复 JSON 键、多个条目、非法数据及超限拒绝。

`crisis_v2_battles.prepare_finish` 在解密和 ZIP 处理前先检查签名中的战斗 ID、自有账号、0039 保存/数据指纹和本地登录，再核对解码后的关卡及日志编队。编队与开战快照的干员、技能、模板及当前未接入的助战/模组选择一致；后续干员升级不会改写旧快照。整个步骤只读，不改变 BattleSession 状态、进度、库存或奖励。

## 实际验证与玩家体验

- `finish-codec-v1.xml`：61 项通过，含 20 项新模式解码及受影响代理/剿灭编码检查。
- `finish-binding-v1.xml`：13 项新账号/保存/编队绑定检查通过；非法账号、数据或新登录在 ZIP 解析前拒绝，处理前后所有表行保持。
- 独立复制已验证的冻结 20 表/五图会话，使用**自造加密请求和 ZIP**核对五图关卡/技能/编队，82 表全行不变，源副本及现用设置/库保持。证据 `finish-binding-frozen-v1/verification.json`。这不是客户端实际发送或原生结算验收。
- 本批共 74 个不同定向用例通过；没有为补记录重跑全量。一次 Ruff 导入排序问题已修正，随后 Ruff/空白检查通过，未重复未受影响的测试。

证据根 `.cache/crisis-20261119/`，汇总 `finish-progress-summary-v1.json`；两组 `mcp-progress-*/`、`rea-progress-*/`，常量/字段对应为 `progress-log-constant-bindings-v2.json`、`progress-native-field-correspondence-v1.json`。曾有一次候选检索过宽且输出截断，随后收窄选择，不把截断结果当完整审计。

玩家端现有入口保持，本批未注册危机合约原生开战/结算路由或重建 EXE。下一把已绑定输入接入结果分类、受信计数、符文/挑战/记录更新和奖励事务，继续补全部评论及领取合同；完成可闭环服务后再成对开放路由并做新的原生代表。
