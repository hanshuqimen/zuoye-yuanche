# 肉鸽首次战斗、生命与自然失败结算（2026-10-24）

## 已取得的实际事实

v16来源f8cc164（业务6ac3e677），在保留原存档的新D副本中第一次实际进入ro1_n_1_4“意外”。没有重走初始化、没有重玩主线或剿灭。moveAndBattleStart真实200，战场/两名局内干员/44敌人显示正常，地图HP4对应战内HP8（含分队战斗生命4）。本场未部署干员，切2倍速后自然失败；不是主动中止。

实际battleFinish包：rank1、interrupt=false、giveUp=false、percent2、killCnt1/validKillCnt1、completeTime51、leftHp0、fixedPlayTime78566。battleLog存在，actionKill为空；三记录和拥有权/局内阵容校验均通过。不能把actionKill条数或总数当成所有有效击杀/漏怪/HP损失。

旧源码只接完美通关，因此该真实请求在产品分支返回501、出现原生提交失败提示；不是QA拦截，不称旧版本失败闭环通过。原存档保留1个STARTED肉鸽战斗，未伪造奖励或结算。

v16共34游戏请求，33×200与1次上述battleFinish501。正常stop且原执行句柄29350实际exit0，所属服务/ADB/index1关闭；57其他账号表、50受保护输入保持，普通战斗0。当前进程脱敏错误类型计数为空，但这不抵消已观察的501。终局未再游玩。

## REA与规则边界

实际战斗结束后读取两页文件映射代码（无堆/认证读），M66437 TakeSnapShot由此前不完整解码变为1364/1364，REA exit0，ev_abccca43d79e24dc0e522febd931a21e7b968afb4addb13d9ec045d998439e48。方法体SHA49066c5ddeb5fbb72103fe290eceffb2c26d5078f7b3dc355457ba46f4aca4da，合并两页SHA1af7cfde8888df4fb5bc31dd8ddc7bf94545be8096b272d81339ef1137d04d2f。默认路径调用GetLifePoint(playerSide)保存剩余生命，不使用混淆的metadata字段偏移猜测。Hotfix路径/全客户端仍未完整逆向。

结合M84576输入HP+shield与分队maxLifePoint增加、M81283当前/最大生命的rank2/3默认判定，以及本次原生8→0观察，新增V2基础生命池结算。护盾0、只有指挥分队战斗生命效果、NORMAL/0、明确普通/紧急变体引用的普通作战才接纳；其他模式/事件、藏品倍率/恢复、护盾和特殊规则仍须单独处理。

受伤胜利采用基础池推导：记录的战内剩余生命与临时生命池一并核对，永久HP最多保留到开战前HP，未用的临时生命不变成永久治疗；rank2与rank3必须和实际剩余生命一致。**尚未取得原生rank2通关及其奖励动画，earn.hp负增量目前是有依据的适配候选，不冒称原生视觉通过。**

## 源码变化

新增版本化`rogue1-ordinary-outcome-local-ticket-v2`，旧V1保留原效果形状和规则摘要，启动/恢复分别重放验证，不重写旧结果。

- 自然失败rank1、非interrupt/giveUp、leftHp0：保存FINISHED战斗和DEFEAT结果、HP归零；EXP/金币/希望/干员等不增加，无掉落/领取，投影GAME_SETTLE及已知EndingBrief/EndingRecord。
- 普通完美/受伤胜利：沿用已经明确标注的社区基础经验/源石锭和本地等职业券策略，保存实际HP变化与isPerfect。没有把这些本地策略提升为官方概率或全部楼层供给。
- HP0不能开始新探索战斗；奖励领取/关闭不能把失败当作通关奖励，也不能提前确认尚未实现的结束政策。放弃只保留独立历史，不补发奖励。
- 探索结束确认、总评分/外部解锁和gameSettle闭环**尚未接通**，不能因为已投影GAME_SETTLE就标完整失败流程完成。

schema0024/70表不变，无新EXE。实际业务摘要见本阶段validation.json；后续UI验证或改动须以账本顶部为准。

## 实际验证

33项相关失败/胜利结算检查24.59秒，另1项临时生命不能治疗的边界1.17秒；Ruff零诊断，各组1既有Starlette警告。早先24项组有重叠，不累计，也未重跑无关全套。

检查覆盖原生形状的自然失败、零奖励、同步delta、重试、HP0阻止、待结束事件、重启和备份恢复、损坏记录启动前拒绝、旧V1兼容、受伤胜利生命边界、rank/HP矛盾拒绝。冻结36普通关×6区域×9基础结果的1944纯计算组合通过；这些是规则上下文检查，**不是官方楼层候选/当前开放条件或所有关卡原生验收**。运行仍只进入已保存且可达的图节点。

真实v16的脱敏字段及原始已验证journal/snapshot在新D `replayed-v16-http` 副本，经本地签发会话重建AES外壳并调用实际HTTP入口：200/新seq重试200，FINISHED、HP0、EXP0、金币6、GAME_SETTLE；重新Runtime相等。原v16 DB SHA0e502cd4866b3b5240456c64d23455aa3a0061b9ff394a2bbcbec3299dbe5b4d保持。**这是脱敏QA重放，不是原始原生密文重发，更不是第二次游玩。** 没有保存认证头或AES遥测。

本地证据：.cache/rogue-native-20261024-v16/{reviewed-results.json,finish-facts-0034.json,loaded-code-receipt.json,summary-0028.json}、.cache/rogue-settlement-20261024/{validation.json,outcome-tests.txt,life-buffer-test.txt,actual-v16-replay-validation.json,rea-stats-loaded/}。官方资源、代码页、归档、DB和截图仅本地不提交Git。

本阶段检查点预登记.cache/github-checkpoints/rogue-outcomes-20261024/，实际远程完成仍以heartbeat-latest.json精确来源/回读/新D恢复为准。

下一步仅观察已保存失败的结束界面/真实结束请求，不重玩本关；补结束确认和评分、退出/中止，再紧急/Boss及非战斗/楼层流程。年龄说明501的独立缺口保留在生命研究报告。完整主题、全部模式、抽卡、成熟发行物和完整验收目标保持未完成。
