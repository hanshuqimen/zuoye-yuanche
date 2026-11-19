# 两类固定进阶券事件来源

完整目标ACTIVE未完成。承接舞会批量接线/private3c07c06，本轮从匹配数据寻找完整奖励来源，不硬加随机收藏品或工具，不重复旧关、剿灭或已有免费进阶原生代表。

## 依据及范围

实际19表e915675d…71ae29仍client_verified=false（镜像v077与冻结CN2.7.71/V070边界保持）。先遣小队choice_up1_1整行hash 66f5190b40bde7f2ab2cf448fb9a253723fd5cf282c682721ce4de6047f4c605，ITEM明确引用rogue_1_upgrade_ticket_5star；高卢老兵choice_up2_1整行hash d19333e255ef533c2f99285a0f17fa1a3507d600d6810d8e4a6551a884404409，引用rogue_1_upgrade_ticket_all，各有明确入场、结果场景。[PRTS事件页](https://prts.wiki/w/傀影与猩红孤钻/事件一览)说明两种免费进阶券，与已接升级筛选目录一致。只接首主题NORMAL/0显式节点，不证明出现权重、层级资格或现实当前活动开放。

复用已有REA而不重复启动提供器：M33706默认计数按四星及以上/upgradePhase0及券职业星级筛选，ev_de4048568831682d563d067f3c375d680d33189658659aa3f9a0098b66e7df45；免费候选及结果字段M154660、M155584/155585和请求构造M153829见[休整进阶报告](roguelike-rest-training-2026-10-25.md)。同一免费进阶已有[原生v30代表](roguelike-rest-native-2026-10-25.md)。最近M150515默认choices/可用bool/additional消费见[舞会REA](roguelike-dance-trades-2026-11-07.md)。这些证据不等于本次两事件或空候选画面已原生验收；Hotfix/间接流/保护offset等原边界保持。本轮0新REA/Android/战斗。

## 实现与当前检查

新增独立惰性rogue_ticket_events程序，显式ITEM引用、完整选择hash、后继和升级规则指纹全部绑定digest。访问决策仍用已有ticket序号账本；固定发放、激活、选择或放弃、结果离开在原事务/拥有权/可达路径内执行。统一ticket_item映射保持旧REST逻辑及旧程序摘要不变；新程序ID明确能力，旧reader不应将其当旧资源事件。schema0036/77不改。客户端不能自选奖励类型、序号或提供余额。

旧REST继续无目标时禁用进阶选项；这两个固定奖励事件发券后由已接筛选器产生候选，空列表可用已有closeRecruitTicket放弃，不能凭空造目标、希望或另一种奖励。该空目标事件处理是本地明确适配；默认免费券列表/放弃合同已有依据，但官方同情形的具体展示仍未原生核对，不宣称已完全一致。所有票券处理前不能离开/推进；同一幂等键返回原收据，新序号对已完成进阶仍409且不写库，不放宽既有晋升限制。

新7个不同检查最终通过：两个有目标免费进阶来源、五星券对六星无候选可放弃、进阶待办屏障、同键及新键重试边界、主阵容/资源不变、结果中途备份恢复/重启、故障500整笔回滚/并发仅一券，以及错票种/序号/伪造来源同步和重启拒绝。第一版动态indirect夹具收集失败0用例；第二版旧training夹具覆盖新场景、第三版基础骨架scene不满足完整目录，各7失败保留。独立完整夹具v4五过两失败，因测试误期望新序号二次晋升200；按既有409合同改断言后只重跑两项v5通过，不重复五项。未通过放宽产品校验消除夹具错误；4文件Ruff已单独核过，原13487句柄后缺失不补造最后ruff退出。Starlette已有弃用警告保留。

当前正在跑相关旧流程检查，下一在新D真实19表副本核旧24用户/77表及两个新来源的完整事务/恢复。尚无冻结HTTP/完整保存恢复/新原生或EXE通过声明；当前源码未提交或进入旧3c07c06包。

证据.cache/rogue-ticket-events-20261107/{audit-v1.json,tests-v1.xml,tests-v2.xml,tests-v3.xml,tests-v4.xml,recheck-v5.xml}及对应失败目录。原始表/存档/日志/凭据/官方代码不入Git；自有生产、测试及记录可保存检查点。


## 2026-11-08 暂停后的实物恢复核对

用户暂停后再恢复，原exec29548已缺失，对应verify_actual_v1.py的Python进程不在；actual-compatibility-v1没有verification.json。只读DB已显示25账号/77表、QA25 SETTLED、五个场景全部FINISHED，原old-restored-new-d与new-event-restored-new-d均存在。不能仅凭目录或状态称原脚本完整成功，也不能重启v1覆盖现场。原退出码和内存中的HTTP请求列表均不可得；不由保存收据补造传输状态/次数。

新增recover_audit_v2.py在全新recovery-audit-v2目录审计已有完整保存，无游戏HTTP或新奖励。68935实际exit0：原舞会24完整用户与77原表仍等于旧基线、原v1的old-restored-new-d全77表同；v1最终25/77与其已有new-event-restored-new-d同。新当前源码加载/全因果账本校验通过，完整25用户/77表在独立副本真BackupService备份恢复、Runtime重启和再次新D恢复均同。所有源DB/settings及两个种子自本次审计开始到完成的字节保持；v1开始前字节摘要已丢失，不补其原字节证明。

QA25票券0–6全DONE。节点3的五星券4只有五星免费候选、节点4的全职业券5只剩六星免费候选，各一个UPGRADE/hope_cost0并有唯一训练记录；节点5再发五星券6没有未进阶目标，空候选已放弃。其显式scene来源、步骤和序号、拥有者/物品、训练前后hash全由当前领域重放验证；不是从累计数字倒推发放来源。主阵容及RLV2外完整用户与发券前种子同，希望cost9/max10、HP4/金币6未被奖励额外修改。结算唯一counts=[0,6,0,0,0,0,2]，6步+2干员合计10分；记录38成功业务收据，绝不称38次HTTP或补造丢失的409列表。旧全部探索/场景/7战斗28报价/关闭结算保持，新增一个显式QA商店使总报价29。主阵容训练、开放前置、6节点方案和免费普通券报价只是QA准备，非自然供给/正式价格。

2个原完整选择hash变异独立拒绝，旧19程序digest与上批coverage-v2完全相同；21程序20唯一choice28场景，不当152/172全接。两个原始完整种子（尚未选择先遣事件、已发空候选券6尚未放弃）均新D加载/全25用户校验通过，无反改SETTLED。

新7检查最终v4/v5合并，与相关76项related-v6合计83不同检查；相关7843实际exit0，4Ruff另跑确认，190源文件AST及diff通过。新业务d08ed7068f5cc98a6e77766a91ab3c60c553b331a05aab57809b8555b003f2f7/190Python、schema0036/77。只有rogue_visits.py、repository.py及新增rogue_ticket_events.py相对上批业务变化。上述是保存与新补验，不回填成原v1传输或退出证明；0新游戏请求/Android/REA/战斗/EXE。

证据recovery-audit-v2/{verification.json,users25.json,all77-table-hashes.json,working-copy,restored-new-d,unselected-event,empty-candidates}；原actual-compatibility-v1全部DB/失败/缺报告状态保留。新事件/空候选具体原生画面、事件资格与权重/全部主题玩法仍未验，完整目标ACTIVE未完成；下一自有源码新私有检查点，旧3c07c06不含本批d08。


## 最终源码与目录拒绝边界

2026-11-08 最终目录拒绝边界补修：自定义固定事件displayData=null此前会抛AttributeError，现明确ValueError拒绝，不放宽完整ITEM/行hash校验。只新增一项针对检查admission-v7通过，不为此重复76已过旧流程或7奖励检查；最终新8+相关76共84不同检查、4Ruff、190AST/diff过。最终业务994b5be18fc853938f98a7c8a9986391d00ea42fdf414b0ada3878437d828bc7，独立recovery-audit-v3/17653actualexit0再次证明原24完整用户/77表、最终25用户77表备份恢复/重启/新D一致，旧19程序digest与源DB/settings/种子字节保持。0游戏请求重放/新Android/REA/战斗/EXE，原v1 exit/HTTP缺失和空候选原生展示未验不变。下一提交和新私有回读检查点。[报告](../roguelike-fixed-upgrade-events-2026-11-07.md)。

最终证明为recovery-audit-v3/{verification.json,users25.json,all77-table-hashes.json,restored-new-d}；v2/d08旧结果和原v1缺报告现场保留。该校验只拒绝非法显示元数据，支持的数据、两个程序digest和旧19程序均不变。尚无新原生展示通过或成熟EXE声明。


## 新私有检查点实际回读完成

2026-11-08 固定进阶券事件私有检查点完成：源b902445cd97662b295b2699aabbcf5ab3b0a440c/业务994b5be1→private8c39a4cd5931df4a576ee7a746f2bfa0a8cb0436，父3c07c06c2982435ca08d52a422380da6502f8522/tree68c35b4add837967c6efd41a6227a06558b62f2d。2598682字节，SHA256 3ea9a039c69c53059e2648d9f6d69a8c1762762ef05646892d5c9e1c41522258、blob680fdfdeed4e296a2d8a63513a9142990540a85d。576历史路径2916UTF8 blob扫描无禁止项/凭据标记，219旧非README项与120677字符完整旧索引含原CRLF保持、新tree222。正常Git禁交互只读probe128/1.481秒无ref，不称codex/development直推；已授权连接器逐blob预期SHA及expected_sha/force=false续main，private/ref/commit/tree/完整README/note实际回读一致。浏览器文件页真实Download事件后立即completion_summary，实际二进制双hash/新D574文件257完整提交及全tree/blob/Prompt/fsck/干净恢复同，核验actualexit0。仅本次新C临时下载核验后移D，不改权限/读凭据/动旧下载；旧3c07c06、所有历史/备份/存档/失败/发行物保持。权威.cache/github-checkpoints/heartbeat-latest.json及rogue-fixed-tickets-20261108/upload-verification.json。包内完整保留84检查/最终25用户77表独立恢复、v1未知退出和HTTP列表缺失、38保存收据不作为HTTP数、空目标本地适配和新事件/空候选原生未验、0新Android/REA/战斗/EXE及完整目标未完成。完成文字晚于包，不重复打包。

下一仅核空候选票券的新原生关闭/返回分支，不重复免费进阶代表或旧关；当前只保存真实完整种子，新代表尚未启动。

## 2026-11-08 空候选原生准备 v1：主页引导未完成

从 authentic empty-candidates-before-discard 完整25账号种子准备独立D副本，业务994b/190文件不变，券6 ACTIVE/list=[]、HP4金币6、7个旧战斗保持。只在新副本设置QA25 profile.flags.progress=100；这只跳过开场战斗，没有设置独立StoryCompletion主页引导。首次启动错误拼接了HEAD参数，源码守卫拒绝且未启动；改用实际git rev-parse后exec81871启动。

006确实显示三项协议。用户明确授权本次QA25；重新查看007已经是FixedTicketQA25主页，队列seq9→10之间只有capture，无模型勾选/下一步，服务器有agreement_version及update_agreement200。不补造由模型接受。008至019仍在主页介绍，最后要求寻访；没有为此抽卡，及时停止保留失败副本。39 HTTP全200、0 rlv2请求、0新战斗，不能称空候选原生通过。81871实际exit0，61其他账号表及原种子/源保护输入不变，所属ADB/index1退出。

证据本地.cache/rogue-fixed-ticket-empty-native-20261108-v1/{prepared.json,authentic-users25.json,prepared-users25.json,requests.jsonl,native-results.json,001至019图片}和.cache/rogue-ticket-events-20261107/prepare_empty_native_v1.py。未提交数据库/图片/日志。下一从这份已停止副本复制新D v2，只显式设置QA25已有QA23的引导完成ID；保持所有探索事实，明确不是自然完成引导，不通过额外抽卡/战斗推进。

## 2026-11-08 空候选原生 v2 关闭、结果与返回代表通过

新副本从已经停止的v1完整25账号DB复制，源DB SHA256 e876cab4f257e429565337925a739431c2a0ec21b8183170f1b3336087c56b11。只在QA25 profile.flags.story加入6个已由QA23使用的引导标记：RO1入口、装备简介及l0-0主页/寻访/编队/战斗UI；这是显式QA准备，不是实际完成这些玩法，也未复制认证数据。原探索run893e9a50-8966-4147-8b0a-eea25c79f32c/节点5/券6 ACTIVE空列表、HP4金币6、两名已进阶干员保持；未发券、晋升、开战。prepare69720实际exit0。

原生56721实际exit0。实际查看008显示“暂无干员”与“放弃”，009为放弃二次确认，010为“先遣小队”scene_up1_1结果，011确认返回地图HP4/金币6/希望剩余1上限10/两名干员；没有进入新节点。29HTTP全200且仅2个rlv2动作：24号closeRecruitTicket(id="6")、26号selectChoice(choice_leave)，均一次；无新createGame/recruitChar/battleStart/抽卡/update_agreement，未触发QA拦截。没有再次接受协议，不重用QA23授权。当前游戏PID过滤错误诊断0019：异常类型/JSON路径/方法名空，Lua nil 0；只证明该次有限采样，不称全流程无bug。

61其他账号表及251保护输入、190源码hash保持；新副本只改变player_profiles/local_sessions/receipts/rlv2_tickets/rlv2_scene_visits五表。所属ADB/worker/server/index1已退出，index0未操作。源码仍994b，未新增产品补丁或EXE。此原生代表证明五星及以下固定进阶券的空候选放弃→结果→地图可消费；不能推广为全职业券空候选、两事件的初始选择页面、官方空资格规则或自然供给。旧REST正常升级原生不重测。

独立存档audit_v2错误使用不存在的RogueSceneVisit.scene_id，触发AttributeError，保留失败目录，不改产品以迎合审计。核实际模型及持久化steps后改为program_id/node5/两步精确记录，audit_v3/80215实际exit0：其他24完整用户不变、QA25主阵容/探索troop/全部property及RLV2外字段保持（仅在线/刷新允许变化），7个旧战斗无新增，run仍MAP_READY/券6 DONE/场景FINISHED/待办空。完整25用户/77表真BackupService create+restore、Runtime重启、再次新D恢复均相同；所有源DB/settings/种子和当前原生DB自审计开始字节保持。0审计游戏请求重放。

证据仅本地：.cache/rogue-fixed-ticket-empty-native-20261108-v2/{prepared.json,prepared-state.json,prepared-users25.json,requests.jsonl,errors-0019.json,summary-0020.json,native-results.json,008至011图片}；.cache/rogue-ticket-events-20261107/{prepare_empty_native_v2.py,audit_empty_native_v2.py,audit_empty_native_v3.py,empty-native-save-audit-v2,empty-native-save-audit-v3/verification.json,users25.json,all77-table-hashes.json,working-copy,restored-new-d}。不提交这些保存、图片、日志及资源。源码b902445已在8c39a4c私有包且回读恢复通过，本次只新增验收文字，不重复同一业务包。下一整理未接事件的完整引用/版本与资格依据，继续按类接线，不重放这个已通过代表。完整主题/全模式/成熟交付仍未完成。
