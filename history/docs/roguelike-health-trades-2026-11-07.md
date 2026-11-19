# 首主题生命换金币事件

当前进度更新：下文准备段落是当时事实；生命交易一个原生代表及完整保存恢复现已完成。018真实选项HP4/源石锭6且花2得8，026确认文字区域后028完整结果，032原位置180ms按压后033-after-held-confirm.png返回地图HP2/源石锭14，第二节点未进入。n27/n37仅selectChoice(choice_trade1_1)、selectChoice(choice_leave)各一次，40HTTP全200/无QA拦截，errors-0024/0035异常、JSON路径、Lua nil均0。无新创建/招募/购买/战斗/放弃/结算或协议接受。021/029短触未产请求，022/030文件名虽含paid/returned但当时未完成，以033画面和真实请求为准；原因待核，不称所有按钮完全正常。

82106实际exit0/ROGUE_INITIAL_QA_STOPPED，实际29800/18443均无，自有ADB/index1退出。187源码/247保护输入/61其他账号表保持，变动表仅player_profiles、local_sessions、receipts、rlv2_scene_visits、rlv2_runs。verify_native_v1.py的69759实际exit0：旧22完整用户保持，QA23与真实种子相比仅当前事件pending/state、HP/gold、节点fts五处同步变化；当前MAP_READY/首场景FINISHED两决策、第二PREPARED空决策。旧探索/场景/7战斗28报价/关闭结算保持，最终23完整用户/77原表真BackupService备份恢复、Runtime重启、新D恢复一致，原生DB/settings和原种子字节保持。证据.cache/rogue-event-coverage-20261107/native-save-compatibility-v1/{verification.json,users23.json,all77-table-hashes.json,restored-new-d}及同名native目录。没有新EXE，显式QA节点不证明自然供给/全主题完成。

本次原生syncData单样914.507ms、syncStatus1876.142ms、syncPushMessage多数约1.6–2.8秒/最大6198.683ms；支付2086.416ms、退出1988.290ms。未达提示词性能目标；QA的RLV2后快照在ms记录之后、响应返回之前，不能当完整等待时间。下一新D无Android副本分别剖析组装/同步/轮询。poll-profile-v1因settings已建profiles而copytree未设dirs_exist_ok失败；v2修正新目录后组装/同步剖析完成，直接app路由查找KeyError停止，原.prof保留。组装约0.68–0.90秒、单次profile中rogue_runs.validated 56次、history_in_session两次构成主要开销；仍需安全消除重复而保留验证/事务隔离，不用跳过校验换取速度。失败副本保留，完整目标ACTIVE未完成。

完整交付目标仍ACTIVE未完成。此前58ed7c6结束页默认配置核查和解包目录修复属于进展；本轮转现有事件协议/事务覆盖，不重打任何旧关或恢复剿灭。

## 审计与依据

按实际19表e915675d8d8a1cc97df8fa46eed27ef1bdaa9d1b0fdb07461dcabda36271ae29核对。原8个已编译程序只包含10个唯一可执行choice，不是目录152个都已实现。第一次覆盖脚本错误地合并program.choices（它保存完整只读目录），已在v2改为frames.branches；错误初稿保留，不据目录存在宣布玩法完成。

当前NORMAL/0可复用SCENE→selectChoice→结果→leave、事务、同步和保存回放；原固定生命/金币/希望、休整及金币换希望保持。新增目标为“迷幻烛火”的生命换金币，完整导入选项choice_trade1_1/2和choice_leave、nextSceneId、类型及显示字段的整行摘要都核对，而不是只解析文本数字。

[PRTS首主题事件页](https://prts.wiki/w/傀影与猩红孤钻/事件一览)实际正文确认消耗2目标生命、获得8源石锭及独立拒绝分支；[Terra Wiki首主题节点](https://arknights.wiki.gg/wiki/Phantom_%26_Crimson_Solitaire/Nodes)搜索返回同名Hallucinatory Candlelights及同效果。[Life Point](https://arknights.wiki.gg/wiki/Life_Point)搜索返回的完整Integrated Strategies段落说明，自愿支付生命后须至少保留1，因此本交易要求当前生命至少3。直接页面读取403保留，没有绕过；此边界为明确玩家规则适配，不声称恢复官方后端成本校验。生命消耗直接扣目标生命，不支付护盾；不将战斗扣血、幻觉或其他主题一概推广。

复用此前[场景协议REA](roguelike-events-2026-10-24.md)和[交易事务依据](roguelike-trades-2026-10-24.md)，不重复反编译未改变的选择组件。本轮没有新的REA进程或原生游戏操作。匹配导入版本与冻结客户端仍有既有差异：19表镜像a550f5e/v077/77.6.0、client_verified=false；不能由本事件行匹配称全表/全部玩法同版。没有事件专属日历开放规则或自然频率的新增依据，事件只作为已保存显式方案接入。

## 源码实现

新增独立程序rogue1-trade-hp-gold-v1：入场两选项，支付hp-2/gold+8且hp>=3，拒绝零效果；各有明确结果场景和退出。三个完整选择摘要分别5963449b…7c1a3、2435ede5…31412、原leave caa928dc…13937；实际19表程序hash 6a2ea88240a72d5b6500ab72eb55928007dba58ef239a5dc5c7c621ca9fdfa54。

rogue_health_trade_events独立惰性编译，rogue_visits只对该程序ID分发。旧fixed/gold-hope/rest程序不因此依赖新行、修改摘要或重算保存。沿已有事务提交决策和两边资源，失败整笔回滚；旧/新序号重试不会再扣生命或再加金币。低生命仍保留拒绝和退出，不把生命扣到0再留在无法退出的场景；客户端不能上传自己的奖励/价格/程序或替换节点。新方案由受信服务准备，不新增万能成功路由。

业务4b6325d98571a3b226346e8583df145cde957169820ea0442adcc871cfc53215、187 Python，仅改rogue_events.py、repository.py及rogue_visits.py。schema0036/77表、旧事件程序策略和既有关闭/评分版本保持；不移植官方代码或新建数据表。新程序ID及保存的程序hash明确能力，旧reader遇未知方案应拒绝，不静默当作旧事件。

## 检查与失败保留

新增模块6项（生命1/2/3/4四边界、结果中途重启备份、故障/并发），使用自有QA文字和事件图，不装作官方数据。8护盾不能替代生命支付；HP3后剩1，HP1/2拒绝付费、仍可离开，完整其他属性保持。同步增量、旧/新序号防重、SQLite触发器注入500整笔回滚、并发两个新序号只一笔，结果页保存、真实备份恢复/重启与后继节点低生命禁用均过。

相关5模块81个不同检查，初次80通过、1个旧迁移表夹具失败：它保留了后加银行两表且仍写目标75。失败目录先完整复制至failed-0025-table-fixture-v2；按实际表引入顺序补移两银行表、目标77后，只重跑失败项通过，不重复其余80。该夹具明确只隔离0025以后表增补及故障回滚，后加列仍存在；不称其为完整历史0025列结构还原，列迁移由独立测试覆盖。此前一次误写不存在test_rogue_rest_training.py在收集前失败、0用例，related-v1.xml保留；按实际文件名改为test_rogue_training.py。最终81不同检查通过、5文件Ruff/187 AST及diff通过，保留既有Starlette弃用警告，不累加重复6项或称游戏零bug。

## 冻结数据API与真实保存兼容

actual-compatibility-v1先核原生工具结算后的原23完整用户/77原表与上次实测基线一致，在独立D副本做真BackupService备份/恢复、Runtime重启、新D恢复都相同。实际新程序成功编译；修改/删除完整选项摘要分别被拒绝，没有更改原GameData。

同QA23新D副本经API创建真实新run，关闭三张初始招募券，显式两个INCIDENT绑定新方案。此地图是QA，非官方自然权重。21次HTTP：20成功200，1次低生命支付预期409且全部表行不变；正常路径无500。第一事件HP4→2、金币6→14、其余属性相同；新序号重试不重复；第二事件付费false、拒绝true，拒绝/退出不改资源。之后主动放弃、gameSettle及重试一致，仅一次2步/2分结算，counts=[0,2,0,0,0,0,0]，无战斗或工具物品分。

旧22完整用户保持，旧7战斗/28商店报价及全部旧场景/关闭意图/结算行保持；原数据和settings字节保持。新最终23用户/77表再次真实备份、恢复、重启及新D恢复全部一致。59434实际exit0。以上是服务器API和保存，不是原生事件画面通过；没有启动模拟器、接受协议、改变客户端或打包新EXE。

保留真实首节点已入场、未作选择的完整native-seed-before-choice.sqlite3，SHA256 60fdf7185dc9087d45196b56f33515116a3c23373cf5670d33291f385930bcb1，以及同时间完整23用户；不是修改SETTLED或由响应拼造pending。下一可在新D再复制此现场，只做一个生命支付/结果/返回地图原生代表，不重新初始化或重打关卡。

当前实际覆盖变为9程序/12唯一choice/17场景，目录仍是152 choices/172场景，不能以此称完整事件系统或自然供给已完成。随机收藏品、招募/特殊战斗事件、全部节点池、幻觉/剧目修正、其他模式、Golden/断网长时/性能/Harmony/成熟EXE等仍未完成。

## 证据与下一步

本地.cache/rogue-event-coverage-20261107/：current-trades.json（错误初稿）、current-trades-v2.json、coverage-after-v3.json、health-trades-v1.xml、related-v1.xml、related-v2.xml（失败保留）、fixture-recheck-v3.xml、failed-0025-table-fixture-v2、verify_actual_v1.py和actual-compatibility-v1/{verification.json,users23.json,all77-table-hashes.json,native-seed-before-choice.sqlite3,native-seed-users23.json,old-restored-new-d,new-event-restored-new-d}。官方数据/DB/保存/日志只在本地，不入Git。

下一先保存本批生命交易与此前Lua目录修复的私有检查点，再从真实种子做单个原生代表。最新已验证远程仍456e1c2/源06a0e79/旧业务85a，本批新4b63尚不能称远程完成；必须实际回读双hash和新D恢复后更新。既过关卡/剿灭不重打，旧失败/存档/发行物/提交保持。

## 本批私有检查点完成

源f3b8cedeb2cd3b30970e0c4a15fca6bdd48d5821/业务4b6325d9已保存至private5c062436ec7f8b7f03eda94d62455f4a51efb253，父456e1c2d4e91927bb9858b55ec12fab830ce006c、tree645296a6d6a1a50b3f0463e27ed2210eb8adab23。bundle2532266字节，SHA256 5869567d2b044f73a4e09c37cf8b3e0c940e60831634e7658544aa3428f9fc54、Git blob cb51908d5715e3add2fae3f1590b6cb770294b2e；README blob6ebf2112f98b3b999057db9cf4f162035eb57dbc、note900ee91464668224e8c48268a0193bad18d08e01。

普通Git禁交互/限时只读probe实际128/1.157秒、prompt-disabled标记、无ref，不打印原始stderr、不提取凭据，也不称源码分支直推。既有GitHub连接器确认private且可push，逐blob预期SHA相同，expected_sha/force=false续main；private/ref/commit/tree/完整README/note实际回读，213旧非README项及117487字符完整旧索引含原CRLF保持，新tree216项。只收自有源码/工具/测试/锁/文档，565历史路径2843UTF8 blob扫描无禁止路径或凭据标记；客户端/资源/GameData/DB/收据/认证/日志/图片未入Git。

授权浏览器打开实际文件页，Download raw file一次语义操作返回本次真实下载路径，随后立即完成CUA completion_summary。核验脚本actualexit0：实际下载SHA256及Git blob双hash相同、新D563文件250完整提交、全tree/源blob/Prompt/fsck/干净状态恢复一致。仅这一个新C临时下载在双hash后移D，不改浏览器权限或旧下载。权威.cache/github-checkpoints/heartbeat-latest.json与rogue-health-trade-20261107/upload-verification.json、restored-remote-f3b8ced；旧456e1c2及全部检查点保持。

包内完整保留81检查的实际失败/定点修复边界、冻结API/真实保存恢复、原生未验、显式QA地图非自然权重及完整目标未完成，也包含58ed7c6的Lua本地目录修复和冻结结束页默认_showTrap=0证据。完成文字晚于包，不另造重复bundle。本轮0新原生/战斗/EXE；下一从真实已入场未选择种子复制新D，做一个生命支付/结果/退出原生代表，不重新初始化或重打。


## 单次原生准备

新D .cache/rogue-health-trade-native-20261107-v1及refresh-diagnostic同名目录已从真实未选择完整种子复制，12326actualexit0。没有再创建探索、购买、招募或开战；绑定仅本地SDK。完整23用户与种子相同，HP4/金币6/首场景ACTIVE无决策、第二节点PREPARED，7旧战斗保持，247保护输入字节保持，APK/资源/TLS/离线/8秒Android配置保持。辅助服务仅允许selectChoice/finishEvent等所需处理，阻止新探索和所有战斗；不覆盖syncData或伪造选择结果。当前尚未启动原生，不能由准备通过称视觉通过。证据native-prepared-v1.json及新目录prepared.json/prepared-state.json/prepared-users23.json；下一只作一次生命支付/结果/返回地图，不处理第二个同类事件。
