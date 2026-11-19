# 剿灭结束请求与周上限视图

本阶段补齐冻结客户端的局部静态证据，并实现同步字段校验、周上限视图和突破奖励候选索引。没有激活剿灭候选数据、接入剿灭发奖事务或完成原生剿灭游玩；完整交付目标继续保持。

## 证据范围

在独立副本运行既有验收程序，仅取得文件映射代码页 `0x3120000/8192B` 和 `0x43D0000/4096B`。SHA-256 分别为 `85af9a578ee3e05218d9673adec96ff048aab76403c190423d5e7501865e051a`、`84fd76eed7b69e81d36bfd0c328d653905a224cd123f1060d06e51b5d717ea78`。父任务随后复核17个相关函数的字节、指纹及解码范围，也核对了观察到的泛型实参和四个字典键载荷。

冻结身份沿用[目录记录](campaign-catalog-2026-10-16.md)：索引 `30c555d4…4804`、metadata `bf14421b…c8b8`、ELF `3ece1e7b…6259`。完整摘要、字节范围和工具输出保存在本地 `.cache/rea-2026-10-16/campaign-contract/parent-followup-audit.json`，原始代码页、反汇编和官方资源不收录源码仓库。

REA native provider 仍不可用，本阶段没有重新安装或 setup；沿用已冻结声明及有界字节分析。下列 M/T/MethodSpec 编号是本地索引引用，不是 REA 服务器签发的 Evidence ID。静态结论限于非 hotfix 路径，不等于已观察真实 HTTP 或还原官方服务端。

## 结束请求

- 新页中 M101850 依据 `InParams.IsCampaign` 选择 Campaign 结束解析和专用发送分支。
- M101835 的 holder 绑定 MethodSpec288726：共享 `_ParseCommonFinishBattleRequest<CampaignFinishBattleRequest>`；发送 holder 绑定 MethodSpec288723，实参为 Campaign 请求和响应。
- 共享解析器 `0x63E4E20..0x63E5268`、发送器 `0x63E4864..0x63E49F8` 的本地 ELF 字节完整解码，不需要为这两处再读取进程页面。
- 解析器建立内部 BattleData：完成时间来自真实游玩时间，嵌套 stats 来自日志快照，签名由同一函数生成；外层 BattleDataInRequest 有独立的字符串字典。两者不能混为一个 telemetry 对象。
- `ComposeBattleRoundFinishData` 的字典键经 holder/literal 绑定确定：`killCnt` 来自 `Scheduler.get_killedEnemiesCnt`，`validKillCnt` 来自独立的 `get_validKilledEnemiesCnt`，`giveUp` 来自解析器的放弃参数，`completeState` 来自调整后的战斗 rank。不能把某个日志中的 `kills`/`killedEnemiesCnt` 替代这些字段。

现有公共结束解码器已保留两个独立击杀字段和整数布尔兼容；新增合成样例验证它不把嵌套日志计数覆盖为结算计数。这不证明剿灭应选择哪一个击杀值发奖，也不证明主动退出、漏怪及特殊敌人的最终计数规则。

实际发送 route literal1824（结束）和此前的1825（开始）仍没有解出。`CAMP_*` 默认载荷给出的五条 `/campaignV2/...` 仍为静态候选，不能登记为已验收 HTTP 路由。两个 Scheduler getter 的内部计数语义也仍未知；若确需继续展开，两个 getter 同在 `0x27DE000/4096B`，本阶段没有新增该页读取。

## 两种突破状态必须区分

M173605 `CampaignFeeViewModel.LoadData` 读取同步的当前周所得和已解锁上限，并计算一个独立的可达上限：

1. 从匹配全局 `initCampaignTotalFee` 开始。
2. 遍历 `open.permanent`，累加各静态关卡的正突破费用总和。缺少玩家实例仍影响可达上限；未知静态关卡贡献零并保留诊断。
3. 只有 `open.rotate` 非空时，遍历 **全部静态 campaignMissions**，累加正的 `breakFeeAdd`，不要求玩家 missions 已有对应键。
4. `isFull = campaignTotalFee >= 可达上限`，不使用本周所得 `campaignCurrentFee`。这是上限成长是否完成的视图。

周上限的待领提示使用 M32985：关卡存在玩家实例、达到击杀档、`breakFeeAdd > 0`、该索引确实存在，且 `rewardStatus[i] == 0`。短数组越过的索引不触发提示。任务提示只认玩家状态精确等于1，且仍受轮换开放条件控制。

奖励列表的候选条件不同：达到档位后，缺少数组项或值非正表示尚未领取，正值表示已领取；费用为零的普通突破奖励也可进入候选。候选索引只描述列表，不代替账号归属、开放条件或原子领取授权。

M173630 的独立指令比较证实任务状态：0未完成，1已完成待领，2已领取。没有将 metadata 默认载荷的压缩字节02/04直接当作线上数值。引用字符串保留 null/空字符串；原生对 rotate 使用 `String.IsNullOrEmpty`。必须使用数组的字段遇到 null 时明确校验失败，不伪装成空数组。

匹配表中初始值1200，camp_02突破费用总和400、camp_03总和100，四个额外任务各25。用人为组合的 `open.permanent=[camp_01,camp_02,camp_03]`、无玩家实例/任务构造纯查询，轮换关闭和非空时分别得到1700、1800。这只是冻结表与算法一致性检查，不代表真实账号开放配置、排期或官服周收益。

## 源码与验证

`protocol/campaign_state.py` 校验七字段同步、六字段 open、实例/任务和独立 sweepMaxKills，并实现只读 `fee_view`、`claimable_break_indices`。Catalog保留不可变任务费用。模型拒绝非法数值、未知结构和必需数组的 null，不写入存档、不发奖。

合成测试覆盖上限成长与本周刷满的区别、静态任务与玩家键的区别、任务0/1/2、负值/缺项数组在两种视图的差别、零费用奖励、空引用、未知关卡、溢出及输入保持。最终完整1015项通过（191.15秒，一项既有FastAPI/httpx警告），Ruff和差异检查通过。验证日志为本地 `.cache/campaign-state-full-final-20261017.txt`、`.cache/campaign-state-ruff-final-20261017.json`；测试数量不表示全游戏完成。

取证副本比较54张表，仅连接用的 local_sessions 变化，36张玩法表保持；227项受保护输入、1079发行文件、数据库和外键检查通过，无活动战斗。服务和测试实例已停止。两次截图尝试的身份检查返回 EMULATOR_TIMEOUT，没有截图成功或原生玩法验收；独立代码读取工具的完整身份检查通过，8秒时限、APK/实例/TLS和离线护栏保持。

## 继续实施

还需真实核对请求路径、Campaign开始/结束响应、完整同步与独立持久化事务，取得击杀、精确合成玉分布/截顶、理智与信赖、突破/任务上限增长、周刷新、轮换和扫荡票规则，再验证原生入口、战斗、结算、领取及重启。19表候选未激活，新代码未打入新EXE。集成战略、卫戍协议、危机合约、剩余寻访和其他主要系统，以及完整Golden、断网、两小时、性能和HarmonyOS验收仍未完成。
