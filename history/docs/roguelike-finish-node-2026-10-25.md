# 肉鸽奖励列表离开入口（2026-10-25）

**当前结论更正**：后续v26实际原生请求是POST `/rlv2/finishBattleReward`，空body，200；类名FinishNodeRequest并不对应finishNode路径。原有路径本来正确，以下“候选入口”假设被反例否定，无依据的finishNode别名已撤回；先前候选501不能叫原生故障。保留重复确认防重/会话与节点守卫改进，按真实路径补验。历史过程保留，不把撤回前的56项全算成最终真实路径验收。

继续按用户效率要求，不重复关卡、不恢复已取消剿灭。楼层方案准备完成后，先纠正战斗领奖返回地图的协议缺口；这不是正式换层实现。

## 客户端依据与缺口

冻结metadata index SHA30c555d4479d4a0f708b9fc61aa4ecfeb945a169e4a82586e31d243afdaa4804与ELF SHA3ece1e7b34165233fe8c3c919cf55dfcb4406b6bbc2725def2b1242b4c0a6259继续绑定CN2.7.71/build190。RoguelikeFinishNodeRequest/T2089本类无字段，ctor M28322/RVA0x3f3b500。扫描可执行PT_LOAD的48,975,762个对齐指令字发现一处直接BL引用0x3eb2160，归属方法边界是M153306/RoguelikeRewardItemListState._HandleOnLeave（最近metadata边界关联，不是仅靠名称证明动态控制流）。

REA静态方法0x3eb2058..0x3eb2240完整488字节，body SHA aac26e66b7760922d08fea046452da9b22cba2999bbb5ffac5323c04437a06c3，句柄66733真实exit0/stderr0，evidence ev_542dcbf7b14d5a53b556522191fd5253af91e5d02bd64682cfd1250da6b83511。默认分支构造上述空请求，再经泛型网络请求和回调；Hotfix/全局符号/末尾terminal-call警告保留。URL字符串尚未由本次原生请求确认，不能仅从类型名断言完整实际路径。

同时检查M151208 DungeonTransitionPendingChecker 568字节只有4字节静态线性解码，没有为它启动REA提供器；不能擅称缺口原因。route_literals查相关名称为空，仅代表该静态索引没有相应文字，不代表客户端没有接口。实际终点/换层合同仍需接着核对。

## 服务端修复

先在自有HTTP通关夹具上运行旧6485631代码，候选/rlv2/finishNode返回NOT_IMPLEMENTED/501。最初按常见404写的诊断分支没有覆盖项目catchall，随后改用实际>=400并确认拒绝前后DB相等；两次红测试保留，不能把首次未执行的只读比较算通过。

新增/rlv2/finishNode，复用真实战斗奖励关闭事务；保留既有finishBattleReward及收据操作名兼容。仅最新游戏会话、当前探索最后访问节点确实为对应已完成战斗、非失败结束、招募券全部处理完时能关闭。未领物品明确放弃，不发到普通仓库。相同或新seq关闭同一末次奖励只确认一次，不移动、不重复发奖；已经进入后继战斗时拒绝用旧关闭请求跳过新节点。初始招募、活跃战斗、场景/商店、失败结束以及未知请求字段都不能用该入口跳过。没有添加万能成功、重置起点或虚构楼层奖励。

首组六项5.90秒通过；补齐真实的后继STARTED记录拒绝和失败结束守卫后，56关联项47.63秒通过（8项新检查，其余结算/失败/事件回归），两组重叠不相加。覆盖delta、同/新seq、两个Runtime并发、未领不发、活跃券阻止、最新会话/账号隔离、事务失败回滚、重开及备份恢复。Ruff最终零，保留既有Starlette弃用及并发场景Pydantic alias警告。本阶段没有新schema/EXE。

## 原生准备与失败

v25新D克隆停机v16并迁移73表后，辅助错误假定原图只有一列且首池只有一个关卡，在HTTP结果/模拟器之前断言中止；事务回滚、原件保持，失败副本保留。随后只读核对原图实际四列、首层五候选、选中ro1_n_1_4；新v26保留该既有明确QA地图，不再改图。

v26在独立副本将旧STARTED记录用人工rank3/percent100/leftHp4加临时生命的规范化结果通过HTTP结算；旧脱敏journal/snapshot只作为有界记录载体。它不是原始原生成功包、不是实际通关或游戏重玩，不用于证明官服结果判定。当前hp4、待BATTLE_REWARD、两项loot未领，原生只观察离开/确认/返回，不进任何节点或战斗。源旧表在准备夹具前除版本保持，55保护输入保持，实际GameData仍e915675d，配置/APK/TLS/8秒Android/index1与所有权守卫保持。

本地.cache/rogue-finish-node-20261025/{tests-before.txt,tests-before-v2.txt,tests-first.txt,tests-related.txt,native-prepare-output.txt,native-prepare-v26-output.txt}，.cache/rogue-floor-20261025/{finish-node-static-calls.json,reward-route-candidates.json,rea-transition/}及.cache/rogue-native-20261025-v25/、v26/prepared.json。业务1f1d087f9593cda4aa65e00dc128484803d0c1e549a59f2b18fa908a2011a7dd。v26尚未启动原生，实际URL/返回视觉未验证。

## v26实际路径和撤回（权威后续）

1a214ab/业务1f1d087f的独立v26运行：成功摘要（人工结果）、两项奖励、离开确认、返回地图均实际消费；第26请求POST /rlv2/finishBattleReward，request_field_names=[]，200。没有/rlv2/finishNode请求。它推翻“FinishNodeRequest意味着finishNode路径”的假设，原有finishBattleReward本来正确；旧候选501不能记作原生路由缺陷。

本次只放弃尚未领取的3金币与1医疗券，返回地图待移动，HP4/金币6/3张已完成初始券保持，没有进入后继节点。34请求全200、1个肉鸽操作，普通开战/肉鸽开战均0。成功摘要只是人工rank3/percent100/生命夹具的呈现，不是本阶段原生战斗或原始成功包。仅变player_profiles/local_sessions/receipts/rlv2_battle_settlements，59其他账号表/55原输入保持；当前进程异常类别计数空。31787真实exit0、所属服务器/ADB/index1正常停止、原PID5456不存在；启动初期一次EMULATOR_NOT_READY和中间黑屏过渡已保留，未反复点击/重放。

随后撤回无依据的finishNode别名，当前业务b7fe8c02168926fe8c6dbe1497d82ccdf6a4550c969a570200c95d13dcc89822。实际finishBattleReward处理逻辑保持本次原生使用的关闭/守卫；只撤回没被请求的候选并纠正文档。新D克隆停机v26，73表全行不变、完整rlv2等于summary-0023，59受保护输入保持；未为别名撤回重复原生。真实的改进是重复关闭及会话/节点守卫，并非修复一个缺失的原生URL。

## 最终关闭检查

用git show取得6485631真实自有rogue_settlement.py，在同一QA状态执行其close：第一次成功，另一seq返回ROGUE_REWARD_NOT_PENDING/409且数据库相等；当前真实路径对同一已关闭末节点200、完整用户同步不变。1项1.93秒通过。最终tests/test_rogue_reward_close.py按实际finishBattleReward路径9项7.49秒通过，并明确检查类型名衍生finishNode候选仍501/不改库；与撤回前56项/首6项不相加。Ruff/diff零，既有弃用警告没有声称修复。

## 楼层pending默认方法

v26只读取所需一个已加载ELF可执行代码页0x3e20000，APK47356684/硬件<test-device>/ELF3ece1e7b仍通过原守卫，不读堆或凭据。M151208/DoCheckPendingValid为568/568字节，body SHA0dfabad67aa1cc43eb97aeac313b4c8780b3f8d94295888b922ba0d5873c10fb；REA已返回完整观测ev_b6756f7a441caeb05394d794bc03e3692b9f3795703a37aec635c3c8f1018bd0，stderr0。

跨自动续接后原执行句柄51388变为Unknown process id，核对原WSL包装进程2564已无对应实例且响应文件完整，没有因句柄失效重新启动REA。未取到其终端退出码，不写成CLI exit0。默认分支EnsurePlayerRoguelike后读取当前player数字状态：不等于2时返回true，等于2时遍历静态注册checker并调用接口，任一true则true，否则false。Hotfix分支坏指令截断/全局符号/末尾terminal-call限制保留；尚未把数字2、3命名或还原具体checker，不据此猜实际楼层推进请求/资格。

本地.cache/rogue-finish-node-20261025/{observed-route-tests.txt,prior-close-tests.txt,prior-close-counterexample.json,native-validation.json,native-v26-reopen/}，.cache/rogue-native-20261025-v26/{requests.jsonl,native-results.json,screen-08..11.png,summary-0023.json,errors-0024.json,loaded-code-receipt.json}与.cache/rogue-floor-20261025/rea-pending-loaded/。下一步按证据继续真实多层游标、按zone记录身份/资源重放、终点与pending资格，不重复已通过的奖励返回或旧关卡。完整主题、其他模式、正式供给及成熟发行验收目标继续未完成。

## 当前私有检查点

2026-10-25领奖关闭检查点ab58474完成：393自有文件/102提交/395历史路径/1317blob，禁止路径/凭据标记0；私有连接器上传023cca2f，原154根项保持。精确提交网页raw回读SHA0380e98f0f69094d770f418162ad14d62a57e03703a23e63ba544eca550b1361，新D393文件/完整102历史/fsck/Prompt恢复相等，句柄77165真实exit0；索引ba4df090精确回读，旧README原正文/155非README项保持。业务b7fe8c02和候选错误/原生反例/撤回/最终9检查/旧源码1反例/34请求原生人工结果返回记录均在包内；未重打关卡或恢复剿灭。当前官方供给、真实多层游标/按层身份/重放及完整成熟交付仍未完成。随后记录文档不预称已在ab包，普通源码分支推送未宣称。实际索引.cache/github-checkpoints/rogue-reward-close-20261025/{upload-verification.json,checkpoint-web-proof.json,restored-remote-ab58474}及heartbeat-latest；未改权限/公开性/凭据、原存档或旧发行物。
