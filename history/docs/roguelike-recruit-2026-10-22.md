# 傀影初始普通招募与重开冷却修正（2026-10-22）

2026-10-23纠正：下文无语音备用候选使用voiceLan:null的兼容推断被冻结metadata的不可空VoiceLangType否定；新输出必须为NONE，旧null仅作持久化兼容。原历史和失败保留，当前依据见[枚举纠正报告](roguelike-recruit-voice-2026-10-23.md)。

按用户要求，停止的剿灭v35不恢复，不重复游玩同一关。当前推进现代集成战略的傀影主题；本阶段是初始化中的普通招募源码、匹配数据与持久化，尚非完整主题或原生验收。

## 冷却反例与纠正

上一阶段0019源码在放弃时写结束水位，并从结束计60秒。它明确记录为本地策略，但与从开始计时的规则不符；撤回其官方等价假设，旧报告和失败证据保留。

[傀影主题资料](https://prts.wiki/w/傀影与猩红孤钻)描述从开始探索计一分钟。冻结客户端的REA进一步核对到：

- M134697 LoadData，0x3983040，708字节全部线性解码，证据ev_a5709cf666e08dea01b56d3a2ed7f52009bc239763c87b00dc32b65ead8a4f3a。默认路径取Outer.record（+0x38）的last（+0x10），加RoguelikeTopicConst.ordiModeReOpenCoolDown（+0x28），写视图lastTs（+0x38）。声明偏移另有只读索引核对。
- M135956 _RefreshData，0x39dacb8，证据ev_97add851882ac65501650d14648e9ef24cdc82e024f29f16f27b7e88cc6531fc，比较lastTs与当前时间，决定重开按钮和倒计时；部分默认分支仍有Ghidra截断警告，不称完整源码还原。
- M134700 _UpdateTopicCommonData读取game.start，写currentStartTs。这个字段单独不能证明record.last来源，以上LoadData和玩法资料共同支持当前适配。

修正后create使用当前账号历史Run.created_at的最大值作为重开锚点。创建及放弃将record.last写为该次开始时间；ended_at只保存结束审计时间，并在虚拟时钟回拨时至少保留created_at。旧结束锚点的outer行在同步时按已保存Run开始时间只读投影，不批量改写旧存档或结束记录。

修改前，新增“满60秒/300秒后放弃立即重开”和“50秒放弃、59秒拒绝、60秒通过”共3项均失败；修正后通过，并覆盖重启和旧记录只读兼容。不能以此前固定时间下的短时放弃通过证明长探索正确。

## 普通招募源码与边界

新增rlv2_recruit_options和rlv2_chars，schema0020_rogue_recruitment，新存档67表。每张券的候选是不可变的独立角色快照，Run角色引用确切券和候选；主账号干员不被转换或覆盖。0019的CREATE限制通过事务内小表重建升级为CREATE/ACTIVE/DONE；0018及更旧升级路径仍保留。失败注入验证表重建及版本回滚，原记录不丢。

接入chooseInitialRecruit、activeRecruitTicket、recruitChar、closeRecruitTicket，复用认证、幂等、增量和事务。每次最多一张ACTIVE券，重复激活保留候选；招募查服务端实际提供的选项并核对剩余希望，角色入队、扣希望、券DONE一起提交。不同序号重放已完成券不会再次招募/扣费；放弃选择不扣希望、不增加角色。closeRecruitChar的独立语义尚未接入，不把它当作另一条万能关闭路由。

数据限定为rogue_1/NORMAL/0、无条件指挥分队、三种基础招募组合的8种普通职业券。职业取表中明确的profession；备用候选取extraCharIds，即使其自身职业与券不同也保留这个明确例外，不按后缀推断、不将所有predefinedChars变为免费候选。普通候选来自该账号真实拥有且可获得的对应职业干员；已进入本次探索的同一个普通实例不重复提供。备用角色不授予到主账号。

charUpgradeTable[0]实际为精一/技能7/专精0。普通干员保留自身较低养成；精二干员进入初始招募时限制为精一阶段上限等级，不能把精二数值等级机械减10。重算技能开放，去掉模组/专精并修正已锁技能索引。明确THIRD_LOW备用干员按基础精一上限快照提供，实际显示仍待原生验证。

现代topic表没有普通希望费用表；适配使用本主题基础费用0/0/0/2/3/6（按一至六星），只适用于上述无修正普通开局。[2022年傀影招募规则资料](https://news.4399.com/xinwen/mrfz/m/954443.html)明确记录二三星0、四星2、五星3、六星6；它是社区玩法观察，不是官方协议或当前服务端快照。旧roguelike_table的五星4希望属于旧模式，未直接搬用。其他模式、分队、藏品修正、临时招募和晋升费用仍未接纳。

所有保存记录在启动写入前检查：阶段/券/候选/角色引用、累计希望、连续索引、主账号来源、技能条件、角色定义及明确备用例外。严格JSON类型拒绝字符串布尔；当前schema缺失两张招募表也拒绝启动，不默默补空。

## 真实数据反例与修复

新D盘v1隔离存档在第一次打开招募时返回VOICE_CATALOG_MISSING。核对冻结19表，五个明确备用干员都没有voiceLangDict和charDefaultTypeDict项；它们不适合沿用普通可获得干员的语音要求。原失败目录/输出保留。

修正仅针对明确备用候选：缺少语音项及默认项时，保留托管string可为空的voiceLan:null；不造JP语音，不放松普通干员的非空语音验证。合成夹具补入无语音备用反例。新建v2目录继续，未修改v1或产品存档。

## 实际验证范围

最终69项相关检查18.28秒通过，Ruff零，一项既有FastAPI/httpx警告。范围为初始化、主题状态、普通招募、备份恢复及0015/0016迁移；此前13/15/64项与最终69重叠，不累计，不重跑未受影响的旧1194全量或原生战斗。

包括基础费用、精二到精一上限/技能锁定、跨职业明确备用、无语音备用、幂等、余额不足和非法选择回滚、账号隔离、双Runtime并发只招一次、活动候选的重启及备份恢复、0019完整记录迁移/失败回滚、缺表和损坏希望/技能/引用/账号来源的写前拒绝、账号删除的角色/候选级联。

实际冻结数据e915675d（客户端2.7.71/build190，资源26-09-22-07-47-20_6c71fa）在新D盘recruit-runtime-v2验证：8普通券逐项审计、3基础组合、45个POST全200，9个探索角色保存，包含真实普通养成上限和明确备用；活动候选的完整同步在重启/备份恢复后相同，最终4账号重启一致，第四账号无探索。三次超过开局一分钟后放弃再开立即成功。integrity ok、FK错误0；原产品DB/settings、旧主题QA、旧初始化QA、开发EXE五输入摘要保持。3-8资格及被选普通干员的养成是隔离QA夹具，不是自然通关/养成。无战斗会话，无Android操作。

真实流程之后仅补充来源校验与删除级联约束：最终69专项覆盖；对v2实际保存记录执行最终代码只读preflight并核对DB摘要未变，没有再跑一遍相同流程。最终业务指纹db09cf94e77c0a2e2842a190a3956853baf6f230aca2a2f29adb0ee63890d9fa。

## 仍未完成及下一步

所有券DONE后仍保留GAME_INIT_RECRUIT，未假造finishEvent或带空地图进入移动。下一步核对初始化完成/地图生成及节点合同，随后接完整主题的关卡与结算。

候选ordinal作为optionId、当前角色字段/结果、响应isAddition/isElite/isFree，以及目前保守设置的upgradeLimited:true，都是待原生验证的兼容适配。暂不支持晋升，不能把这个限制说成官方等价。REA M153827 SelectRecruitChar（ev_1449f1f1cbd728a520d41d57cfe92f8fc0ed479e4143201845b60cd77c483b1d）揭示选择上下文创建；M153870回调（ev_9f1c9b7b963ffde4f5d2df158eb95198eba19e1ca5d4a7e3e59908bad60cd37c）有坏指令截断，未给出完整请求组装证明。第三方参考仅用于定位差异，其希望0/全员、精二等级减10等捷径没有照搬。

随机临时招募、助战、晋升、条件组合/分队、其他难度/主题、初始化完成、地图、节点、战斗、奖励和结局均未完成。未新打包EXE、未做这段原生视觉验收；完整游戏、Golden、断网、两小时、性能和HarmonyOS目标保持。

本地证据索引：.cache/rogue-topic-20261022/recruit-validation.json、recruit-runtime-verification.json、recruit-final-regression.txt、cooldown-before.txt及rea-reopen/rea-recruit-selection。原始游戏表、反编译输出、DB和日志不提交Git。远程检查点索引为.cache/github-checkpoints/heartbeat-latest.json，当前阶段准备目录rogue-recruit-20261022，必须实际回读/恢复后才记为远程完成。
