# 普通招募事件来源核查，2026-11-08

首次仅完成来源核查，下文保留当时事实；最新源码、检查和真实恢复结果见末节。上一空候选关闭代表已通过且停止，不重放它、不重打旧关。完整交付目标继续。

## 实际版本和依据

读取真实导入19表e915675d8d8a1cc97df8fa46eed27ef1bdaa9d1b0fdb07461dcabda36271ae29、镜像a550f5e/v077/77.6.0；冻结客户端CN2.7.71/V070，client_verified=false。在刚完成的empty-native-save-audit-v3/restored-new-d中加载当前Runtime读取choices/choiceScenes/recruitTickets，没有请求游戏HTTP、修改种子或启动Android。这里只核首主题rogue_1，不把当前显式NORMAL/0测试编排当官方当前开放/自然资格。

本次实际打开[PRTS事件一览](https://prts.wiki/w/傀影与猩红孤钻/事件一览)，与本地完整行交叉核：委托冒险者支付5金币取得普通全职业招募券；皇家争执支付8金币取得保证专属临时干员的特殊全职业券。网页是社区规则依据，不是服务端源码或资格/权重证明。表description、ITEM引用及完整行摘要进一步约束适配；不能把描述中的随机词转成自选概率。

复用已取得REA M33709职业/星级过滤、M33666/M33667普通券消费者及招募/进阶请求字段证据，见[普通多职业报告](roguelike-ticket-variants-2026-10-26.md)、[付费晋升报告](roguelike-paid-promotion-2026-10-25.md)。未新开REA会话，也未据此称事件支付金额/随机池已经逆向；客户端过滤不提供后台自然供给权重。

## 核到的完整引用

|选择|完整choice SHA256|后继/券|当前结论|
|---|---|---|---|
|choice_recruit1_2|3ad33fb0c1a9c786995568da1f1138288aed34da732c8d22ef6d58d30e5a3d43|scene_recruit1_2 / rogue_1_recruit_ticket_all|支付5的固定普通券来源，尚未接事件发放|
|choice_recruit2_2|0ee2941528070fc6a1aefc061543ea677ed9941a41f9b250ff67e9abd5a75f66|scene_recruit2_2 / rogue_1_recruit_ticket_all_premium|支付8的特殊券，不能当普通券|
|choice_recruit1_1|07bab6f32323523091cb7de6d184a8a56e6f542471a7a8600beda5bd84718ef0|scene_recruit1_1 / TRADE_PROB|随机2职业，未取得分支/职业抽样供给依据|
|choice_recruit2_1|cb5d11d7ed16c7421d5d1a94dde6c84922f82aff04ad9642e2cecbd89d50415a|scene_recruit2_1 / TRADE_PROB|同样不能用全职业券替代|
|choice_recruit1_3|aad855ca329e581b55fa61c200cad88bb357bf39107295447175b751b171f495|scene_recruit1_3 / NEXT|独立离开叙事，不能凭ID授予物品|

两个all券的profession639/全部8职业/全部6星级与5个THIRD_LOW备用相同，但premium extraEliteNum=1，plain=0。当前普通目录有plain all；special目录单独承认all_premium，elite_scope要求可信供给显式声明范围，拒绝把全局predefined集合当自然池。相关[精英供给报告](roguelike-elite-supply-2026-10-26.md)，此阶段未重读/重测其全部旧证据。

当前rogue_visits.choose已经在同一事务写步骤/票序号并激活，grants和完整保存重放绑定来源；其映射现在只包含REST和两固定进阶事件。新增普通券来源应有独立完整事件图/支付门槛/规则摘要，复用该事务路径及已有普通招募、候选和付费晋升逻辑，保持旧21程序digest。未据此断言直接加映射即完整可用。

## 可重复下一步

先只接有明确金额与固定ITEM的choice_recruit1_2，完整验证余额5边界、原子扣款发券、待办屏障、候选及主阵容隔离、相同/新序号重试、来源篡改拒绝和结果中途真实备份恢复。不为补记录重跑旧空券或免费晋升原生。初始菜单缺TRADE_PROB分支时须明确是受信固定方案，不称完整委托事件或自然供给；未知分支显式拒绝。premium需先恢复其事件专属精英候选范围来源，再接8金币事务，不使用plain券替代。变更后仅补受影响检查及冻结完整保存/新D恢复，源码提交和下一私有回读检查点按账本约定执行。

## 固定普通来源实现及实际检查

独立rogue_recruit_events程序rogue1-event-recruit-all-paid-v1，入口保留已核固定支付与真诚拜托叙事出口，两个结果都经choice_leave返回。绑定两完整choice SHA/固定ITEM/精确后继，支付最低金币5、Delta gold=-5；摘要包含完整普通券/物品/养成上限/正常招募与晋升费用。通过repository惰性加载，旧21程序digest不变。共享rogue_visits事务只加独立来源映射：步骤、券序号、扣款和激活原子提交，已有持久化重放及未完成券屏障覆盖新来源；不新增表/迁移，不增万能成功路由。明确受信变体，尚缺原事件第三个随机2职业分支，不能当自然完整事件。

业务c0b86ef7c1b2bacef4725d5d19843eed9054a66504a023a69c88405819ececb6，191Python、0036/77。9个新增检查最终分别通过：支付4/5门槛、普通候选0/2/3费用、希望不足400/不变、招募2希望/主阵容隔离、相同键及新键重试、待办屏障、结果中途备份、重启、故障500全回滚/并发仅一券、premium/错误序号/缺来源损坏拒绝、null/特殊ITEM拒绝。v1四过五失败因QA缺完整进阶目录，普通券会生成付费晋升候选；补夹具后只补跑五项v2四过一失败。该项先错误比较新增成功收据前后的完整DB，再误期望普通招募希望不足409；按既有400/ROGUE_HOPE_REQUIRED修正，v4单项通过，不放宽产品限制。v3失败与全部XML保留。

相关四文件v5为61过1失败：旧0019迁移测试硬编码65/75表，当前应67/77。修正测试为准确声明表集合减该降级明确移除的10表，保留完整旧行/票券列迁移和真实操作核对，仅该项v6补过；无产品schema变更。合计9新+62相关=71个不同最终通过，5文件Ruff/191AST/diff通过。既有Starlette httpx弃用与Pydantic alias警告保留；失败输出的自有QA token/收据仅在本地缓存，不提交。

## 冻结真实保存、事务和恢复

actual-compatibility-v1在新游戏请求前把仅有两项的新券摘要误当21旧程序全集，v2又误把EventProgram.choices全目录当成仅本图的三选择，均实际exit1、保留；核数据结构后v3合并旧19+固定进阶2摘要，并按frames.branches统计，15849实际exit0。不是通过改产品、原保存或重跑游戏消除审计错误。

原完整25用户/77表及旧21程序保持，经真实BackupService create/restore、Runtime重启、新D恢复均相同。仅独立副本新增RecruitEventQA26，显式准备3星先锋/6星风笛、主阵容E2养成/关卡前置和两节点方案；这不是自然地图、实际通关或原生验收。实际27HTTP：23成功/4预期409，无其他状态；请求delta均与完整sync相符。首次6金币支付到1，唯一新券3 ACTIVE/普通全职业，6星风笛候选人口6/P1，完成招募扣6希望；同键回放与新键重试不重复扣款、发券或招募，待办未解不可离开。支付结果中途真备份恢复并独立新D开存档同。第二节点余额1，支付及未接随机选择各409/原DB不变，可走叙事出口，保持4券总数、金币1和希望cost6/max6。主阵容保持，探索新增成员符合普通券事务；一次结算counts=[0,2,0,0,0,0,2]/score6，重复结算不增进度。

最终完整26用户77表真备份恢复/Runtime重启/再次新D恢复均同；旧25完整用户、探索/场景/7战斗29报价及旧关闭结算保持。原DB/settings/原空券种子/上一原生DB字节不改，源码hash保持。22程序22唯一choice31场景仍仅显式合同覆盖，不是全152/172或自然池。新真实完整未支付种子native-seed-before-paid-event.sqlite3，SHA256 a1e2ba6f647cd226ce2b5a0eacab92ea6e949796b29499b23a350df4e5e0bf35，另存完整users26；不反改最终SETTLED。0新Android/战斗/REA/EXE，具体新入口选择画面未验。

证据仅本地.cache/rogue-recruit-event-sources-20261108：tests-v1/recheck-v2/recheck-v3/recheck-v4/related-v5/migration-recheck-v6.xml；verify_actual_v1/v2/v3.py及actual-compatibility-v1/v2/v3；最终v3/verification.json、users26.json、all77-table-hashes.json、working-copy/old-restored-new-d/paid-result-new-d/final-restored-new-d与上述真实种子。数据库、资源、收据、日志、缓存均不提交。下一先保存自有源码私有回读检查点，再处理剩余事件随机/特殊供给依据；不重复已过原生分支，完整系统/所有模式/Golden/断网长时/性能/Harmony/成熟EXE未完成。

## 私有检查点已完成回读

源5a6694749bc7d9d4cf59be8a0a4b701468e0409a/业务c0b86ef7已保存private ba7ecbfb7bf4d39e59f296266f37501dc65ee7f6，父8c39a4cd5931df4a576ee7a746f2bfa0a8cb0436，tree d8a7385043f7b356b2ae95efa23cf1c25fd35e4b。完整bundle2623429字节，SHA256 6d7278f381e442194f645446dc305b6421b923d8e21c6cfe7a254a7f302830bb、Gitblob97789df2c583656f7c9371732742d4210e03ec7c。579自有文件/262完整提交，581历史路径/2959UTF8blob扫描无禁止项或凭据标记；221旧非README项、121796字符完整旧索引含原CRLF保持，新tree224。正常Git禁交互只读probe128/1.032秒无ref，未声称codex/development直推。通过已授权GitHub连接器按每blob摘要、expected_sha/force=false续main；private/ref/commit/tree/完整README/note实际回读一致。

浏览器仅真实文件页下载（先登记download事件、按新AX69点击、返回实际文件路径和当前AX、下一调用立即completion_summary），没有网页上传/修改权限/接受协议/读凭据/访问8080；不补造截图证明。实际入站二进制双hash通过，新D restored-remote-5a66947完整tree/blob/262历史/Prompt/fsck/干净恢复相同，verify_remote actualexit0。仅本次新C临时下载在双hash后移D，其他下载和旧备份/保存/失败/发行物保留。prepare64893实际exit0；.cache/github-checkpoints/heartbeat-latest.json和rogue-recruit-events-20261108/upload-verification.json为权威，另存remote-api-verification/received-web/完整恢复目录。包包含本报告到前节的实际71检查/26-77恢复及所有未完成边界，当前完成文字晚于包，不因纯文字重复打包。

下一优先核事件随机两职业待办的REA请求/数据消费者与后台资格来源，不能拿普通全职业券或已有初始招募组合替代；premium保证精英的事件范围保持独立未知。当前无自有worker/REA/Android待续会话，具体会话恢复仍以实物为准。完整目标ACTIVE未完成。
