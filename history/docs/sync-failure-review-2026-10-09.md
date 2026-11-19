# 数据更新失败审计复核

复核日期：2026-10-09（Asia/Shanghai）。
本会话早先读取的原报告实际位置：`D:/CODE/VibeCoding/sync-failure-analysis-2026-10-08.md`。
用户所列 `TerraLocal/docs/` 路径没有该文件；本轮继续核查此前复核记录与本地原生证据。

结论：报告提出的受控验证方向有价值，但不能按其 7.3 / 7.4 代码直接修改。
这两项与冻结客户端的类型契约冲突，不能作为修复。后续受控验证已定位到本样本的跨日刷新失败：
刷新完成后 lastRefreshTs 仍回退到账号创建时间，客户端再次判定跨日并主动弹出错误。
依据用户此前“优先修复数据更新失败”的要求，已修正服务器刷新事务；独立存档的真实客户端验证通过。
正式存档与资源未为这些副本试验改写。完整游戏验收仍未完成。

## 1. playerDataDelta 不是多余字段

报告只检查 `PlayerSyncStatusResponse` 自身声明的字段，漏掉继承关系。
冻结类型索引的查询结果为：

```text
Torappu.PlayerSyncStatusResponse : Torappu.PlayerDeltaResponse
    declared: ts → long
    declared: result → Dictionary<long, JObject>
Torappu.PlayerDeltaResponse : object
    declared: playerDataDelta → Torappu.PlayerDataDelta
```

因此只看到 ts / result 不能推导出完整响应只有两个字段。
`data/research/client-native-sync-contract.json` 当前确实只导出声明字段，未包含父类型；
使用这份局部清单作完整契约是报告的关键错误。
删除增量会使刷新期间已落库的理智、商店等变化无法通过本响应同步给客户端。
`tests/test_status_refresh.py` 已包含理智恢复后应用增量与完整快照一致的检查。
报告所称“零风险附带修正”不成立，应保留增量并检查其实际应用过程。

## 2. mainStageProgress 不能改成章节字典

冻结索引中 `Torappu.PlayerStatus.mainStageProgress` 的类型为 `string`，不是字典。
已校验的原生 `StageDataUtil.GetMainStageProgress` 普通分支读取该字段，
并将其传入 `GetStageIgnoreTime`。应继续确认其所代表的关卡及进度语义。

报告 7.4 返回 `{zoneId: {state, zoneId}}`，与字符串字段不兼容。
当前 GameData 的 15 个 MAINLINE zone 全部没有报告代码使用的 `stages` 字段，
所以该算法也没有取得关卡记录，只会为各章计算默认状态。
主页错误显示“全部完成”是已知问题，但“50 级 / 全干员 / 满理智与 null 矛盾，
因此触发一致性校验”没有找到对应客户端检查，不能用于证明本次弹窗根因。

## 3. rawPlayerData 假设尚未成立

原生闭包确实存在“非空增量且 rawPlayerData 缺失”时的异常分支。
发现这条分支，只能证明需要检查该条件，不能证明实际失败请求走到这里。
此前在弹窗状态下的有界检查观察到 PlayerDataModel 和 rawPlayerData/JObject 均存在；
这个采样不能排除处理过程中曾短暂缺失，也不能证明模型已完整初始化，
但不支持报告第八节把“初始化前提缺失”写成确定根因。

空增量组不会满足同一个“非空增量”前提。三组相同弹窗可能来自不同分支；
移除全部 result 还可能另外造成回调失败。
正确表述应为“已尝试的响应修改没有消除弹窗”，不能表述为“排除了响应内容这一层”。

## 4. 逐模块试验必须修正分组

报告第 4 轮的 2047 包含 32 / 128 / 256 / 512 / 1024，却不包含上一轮的 2048。
其中 256 是当前明确未支持的 SYNC_CRISIS，不能作为仅加入 1 / 2 / 8 / 64 的试验。
保持原计划的递增关系，掩码应为：

```text
4 → 20 → 2068 → 2143 → 3807
```

还必须控制真实客户端的请求或实际执行路径；修改单元测试里的 modules，
不会改变已安装客户端发出的 3807。缺失模块结果的试验也不能等同于未请求该模块。

## 5. 可保留的建议与验证限制

- 保留冻结版本、独立测试存档、逐变量比较、截图和脱敏日志，以及真实客户端复测。
- 继续检查反序列化、增量应用、数据变化通知和状态同步回调，取得错误类型或明确失败条件后再修改。
- HTTP 200 证明服务端处理了对应请求，不能证明客户端解析、应用或后续请求均成功。
- 18 张表加载成功不能证明客户端所需数据与所有字段完整。
- UISyncDataUtil 的静态内存状态可先通过进程冷启动重置；没有证据表明它们持久化在资源缓存中。
  不应先清除已准备好的游戏资源，以免引入重新下载等额外变量。
- `PlayerProfile.registered_at` 在 `domain/accounts.py` 创建账号时取服务器时间；
  报告将其解释为“兼容配置生成时间”不符合实现。

上述第 1–5 节为初次静态复核的判断。其后已启动独立测试实例，并继续验证下述实际失败条件。
临时日志插桩已经恢复；修复验证使用冷启动后的客户端，未修改客户端函数或错误分支。

## 6. 后续验证定位了实际失败条件

冻结客户端普通分支的调用关系为：

```text
UISyncDataUtil.CheckIfCrossDays  (0x33BDBE8)
    → DateTimeUtil.IsSameDay(currentTime, PlayerStatus.lastRefreshTs)
    → 不在同一游戏日时返回 true

HomeMainState.<_SyncPlayerStatus>b__100_0  (0x3BF1EEC)
    → 本次刷新前判定跨日
    → 响应应用后再次 CheckIfCrossDays  (0x3BF2014)
    → 若仍跨日，取 ALERT_SYNC_STATUS_CROSS_DAY_FAILED  (0x3BF2038)
    → 显示错误弹窗并要求重新登录  (0x3BF20E0)
```

这条失败路径不需要发生反序列化或 rawPlayerData 异常。
IsSameDay 原生代码分别对两日期 AddHours(-4)，与国服凌晨四点的游戏日边界相符。
此前失败进程中，跨日失败 getter 已初始化，内部错误与登录全量同步失败 getter 尚未初始化；
修复后冷启动进程中跨日失败 getter 未初始化。该观察与实际截图、增量及落库结果相互印证。

失败副本的冻结服务器时间为 1791503812，账号创建时间为 1791384027。
PlayerProfile.flags 没有 lastRefreshTs；SyncDataAssembler 回退到 registered_at，
而服务器刷新流程原先没有任何地方保存新的 lastRefreshTs。
因此即使 syncStatus 返回 200，客户端刷新后的跨日判断仍为 true。

### 受控比较

| 试验 | 改动 | 客户端结果 | 能证明的范围 |
|---|---|---|---|
| 失败基线 | 旧刷新流程、原副本与固定时钟 | 数据更新失败 | 此输入能够重现问题 |
| 单条件试验 | 仅将独立副本的 lastRefreshTs 写成冻结时间，再冷启动 | 主页没有失败弹窗 | 刷新时间条件与弹窗直接相关；手工写值不作为永久修复 |
| 服务器修复试验 | 从修改时间前的同一数据库备份重建副本，保持时钟；仅换修正后的服务器流程 | 完整 3807 刷新后正常显示主页 | 旧全量快照经服务器增量刷新后可通过真实客户端检查 |

服务器修复试验在 2026-10-09 00:26:49 UTC 收到 modules=3807。
返回增量根字段为 pushFlags / status；没有省略模块结果或增量。
lastRefreshTs 从旧账号创建时间更新到 1791503812，revision 从 564 增加到 565，
registerTs 不变，本轮请求全部为 200。截图 result.png 显示主页，没有更新失败弹窗。

随后从成功存档创建新副本，重启服务器并将副本时钟推进一个游戏日。
00:32:44 UTC 的 3807 刷新把时间从 1791503812 推进到 1791590212；
00:33:09 UTC 同日再次登录刷新只返回 pushFlags，没有再次推进刷新时间。
主页截图显示下一游戏日，未出现更新失败弹窗。
期间另有教程提交和公开招募调用；`/gacha/syncNormalGacha` 返回 501，公开招募仍未实现。
这项错误保留在验证回执中，不能把本轮记为“所有请求成功”或完整游玩通过。

### 修复方式与边界

- 完整刷新包含已观察到的 3807 模块且 prepare 验证成功后，在同一事务中更新持久化刷新时间。
- 先取变更前快照，再做理智恢复与完整刷新确认，最后取变更后快照并生成 playerDataDelta。
  时间更新因此能送达客户端；没有把序列化时的当前时间伪装成存档状态。
- 同一游戏日的重复请求不重复写时间；部分模块请求不确认完整刷新。
- 已有但尚不能结算的基建、活动、蚀刻章等仍明确失败，失败事务不推进刷新时间。
- 时钟回拨可更新刷新确认时间，保留历史任务领取和购买记录，不补发奖励。
- 任务与商店的周期选择使用本次事务捕获的同一个时间，避免凌晨四点操作中途切换周期。
- 完整刷新比较前一次确认周期与当前周期，发送旧任务的删除和新周期任务变化。
  单元测试覆盖持有昨日快照的客户端和已取得今日全量快照的客户端；历史领取记录保留。

新增 20 项回归，覆盖真实刷新掩码、凌晨四点、部分刷新、并发/重复请求、账号隔离、
服务器重启、时间回拨、旧任务增量删除、异常时间及响应组装失败回滚。
最终完整回归为 128 项通过，46.05 秒；修改文件 Ruff 通过。
这些结论仅证明当前版本与这些存档条件下的刷新问题，不代表基建等未实现系统或成熟发行已验收。

### 正式本地存档与 Windows 程序验证

已保留旧发行目录并重新生成 Windows 程序。初次打包后使用正式本地存档及实时服务器时钟验证：
00:39:51 UTC 的 syncStatus 返回 200，客户端显示主页，没有更新失败弹窗。
账号创建时间仍为 1791384027，刷新时间由正常刷新流程保存为 1791506391。
正式存档的任务记录为 0；真实任务界面仍未验收，任务增量结论来自结构一致性回归。
启动前已创建 `manual-20261009T003622.224589Z.sqlite3` 备份，未手工改写正式刷新时间。
version、doctor、backup、TLS 游戏服务和管理服务启动检查通过；doctor 的全局 client_verified / ready_for_play 仍为 false。

将任务周期增量补充打包后，再次重启最终程序并冷启动客户端。
2026-10-09 01:01:22 UTC 的 syncStatus 为 200（38.33 ms）；此前登录和 syncData 也为 200，
截图 packaged-final-result.png 显示主页，没有更新失败弹窗。最后 EXE SHA-256 为
`212e6004d5efdbebbe2eceaa2b3838d93a865fcd54a8eada90ee2a08e3b16015`。
新目录的 data 是指向工作区正式本地数据的目录链接；没有复制官方资源进发行程序。

## 复核依据

类型与字段来自 `.cache/client-metadata/official-index.sqlite3` 的只读查询：

```sql
SELECT full_name, parent FROM types
WHERE full_name IN ('Torappu.PlayerSyncStatusResponse', 'Torappu.PlayerDeltaResponse');

SELECT t.full_name, f.name, f.type
FROM fields f JOIN types t ON t.id = f.owner
WHERE (t.full_name = 'Torappu.PlayerDeltaResponse' AND f.name = 'playerDataDelta')
   OR (t.full_name = 'Torappu.PlayerStatus' AND f.name = 'mainStageProgress');
```

索引冻结 metadata SHA-256：
`bf14421bbafe9c71d944ba4f97b31ecd666232640eac0829db3d84ac716ac8b8`。
索引冻结 ELF SHA-256：
`3ece1e7b34165233fe8c3c919cf55dfcb4406b6bbc2725def2b1242b4c0a6259`。
GetMainStageProgress 原生切片 SHA-256：
`a2799bb0699b933319a55ce4dc4e6e5feb441e37bb262067557c984ffd719047`。

跨日检查切片 SHA-256：
`b14570537b6aa85956acfd2af2e04b2742a7b72e191414e64f0cc45d6b576e78`。
主页回调切片 SHA-256：
`b297f75bce10d6df6054086e1b3d663f961c183fb49f5e12f3088d04e104d346`。
游戏日比较切片 SHA-256：
`0b4d435f03bd113ea270422f64d84f562c1b201f35efd7e23b8b3e58290e90e9`。
同输入修复试验数据库备份 SHA-256：
`3ca08a9978211113fcb0634d40f2835cc106798145d1b31feadeab67201e220e`。
真实客户端验证回执：`.cache/refresh-diagnostic/frozen-refresh-fix-oct09/client-validation-first.json`。
再次跨日验证回执：`.cache/refresh-diagnostic/frozen-refresh-next-day-oct09/client-validation-next-day.json`。
正式存档初次程序验证回执：`.cache/refresh-diagnostic/packaged-formal-initial-validation.json`。
最终程序验证回执：`.cache/refresh-diagnostic/packaged-final-validation.json`。

## 本轮复核

原审计文件当前不在用户所列路径或此前读取的实际位置。本轮对照此前保存的审计复核记录，
重新查询冻结客户端类型、检查现行实现及验证回执；没有把缺失原文件视为已经重新全文读取。

- 再次确认 `PlayerSyncStatusResponse` 继承 `PlayerDeltaResponse`，父类型声明 `playerDataDelta`。
- 再次确认 `PlayerStatus.mainStageProgress` 为 `string`。
- 三份跨日原生代码切片、最终程序和最终客户端截图的指纹均与验证记录一致；
  截图显示主页，没有数据更新失败弹窗。
- 本轮重跑跨日和状态刷新相关的 27 项测试，全部通过（4.02 秒）；
  上述 128 项为此前完整回归结果，本轮没有重新执行完整回归。
- 更正额外 501 请求的名称：`normalGacha` 对应公开招募；`advancedGacha` 才对应寻访。
  这项未实现流程与跨日刷新修复的验证范围分别记录。

因此仍建议保留报告的受控定位方法，拒绝直接套用删除增量和章节字典两项修改，
使用已落库、通过增量同步给客户端的完整刷新时间作为本次问题的修复。

### 2026-10-09 再次核验

本次用户再次要求阅读原审计。给定路径及此前记录的实际位置均未找到原文；
以上对原报告建议的归纳来自既有复核记录，不能视为重新读取了原文或核验了新版。

- 再次只读查询冻结类型索引，父类增量字段与主线字符串类型均与上述结论一致。
- 再次检查当前刷新事务、固定事务时间与凌晨四点周期边界；确认完整刷新后保存时间，
  并由前后快照生成时间增量，部分刷新及失败事务不确认完整刷新。
- 重跑跨日及状态刷新相关 27 项测试，全部通过，耗时 3.40 秒。
- 三份跨日原生切片、最终程序与最终主页截图的 SHA-256 均匹配原验证回执；
  重新查看留存截图，显示主页，没有数据更新失败弹窗。

本次没有修改游戏代码、存档或客户端，也没有重新进行模拟器复测。
实际客户端通过的结论依据此前受控试验及留存回执；不扩大到其他未验收流程。

## 2026-11-19 增量与保存的 JSON 类型一致性

用合成状态复现两个问题。布尔值改成同值整数时，旧增量比较漏掉改动，嵌套数组也会漏报。只修复增量后，写入响应已显示新值，但独立读取 SQLite 时仍是旧类型，因为 ORM 也使用了普通等值比较。

增量和 `PlayerProfile.flags` 的赋值现在共用保留类型的比较。数组更新仍整项替换。SQLite 表结构、列类型与版本沿用原配置。复核失败夹具中保存的是 `true` 和 `0`，响应却是 `1` 和 `false`。修复后实际数据库、新前台快照与写回回执均为新类型。

90 项相关检查通过，覆盖状态投影、同步增量、事务、跨会话重试以及备份恢复。D 盘证据位于 `.cache/sync-json-types-20261119`，其中 `before-982d2v9d/reproduction.json` 保存原增量缺失，`verified-storage.json` 对比实际旧库和修复后值，`tests.xml`、`flag-tests.xml` 记录检查结果。第一次保存层测试用了未投影的字段，改为合成已投影字段后确认保存缺陷。验证范围为源码与合成状态，原版客户端的历史提示是否受此问题影响尚待实测。
