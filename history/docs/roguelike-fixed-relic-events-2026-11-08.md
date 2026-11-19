# 固定属性收藏品事件来源

开始时记录（当前结果见末节）：当时尚未实施或通过。基线253e09a、业务c0b86ef7/191Python/0036-77；原22程序/26账号77表保存保持。仅rogue_1 NORMAL0，当前主题已开始并归档，不代替账号资格或自然事件生成。

先前邪恶之棺/以血还血链中m07增加战斗金币30%，公开资料与表没有确定整数取整方式，精确搜索未补到可靠依据，未猜测接入。保留该完整链未实现，转向已有完整效果支持的石中剑(m04/m05)、暗门(m13/希望2)、密室(m14/生命3)。PRTS具体事件与收藏品页和当前实际导入完整choice/ITEM/属性定义交叉核对，原始数据仅D缓存。数据e915/v077/77.6.0仍client_verified=false，对冻结CN2.7.71/V070不称全表同版。

实施目标：固定来源到库存、按真实节点顺序的获得重放、重复拒绝及请求幂等、图鉴发现、普通战败/Boss/主动放弃的收藏品计数；复用已支持属性，不发到主阵容，不新增默认随机池。三完整图的自然出现权重/开放资格仍独立未知；受信方案单节点绑定，重复图限制若加入是本地准入策略。新来源需分别验证事务、重启/恢复和损坏拒绝；按用户效率要求不重打旧关。

本地.cache/rogue-fixed-relic-events-20261108/source-audit-v1.json保存六完整choice哈希、四完整属性/ITEM/archive、精确场景及旧22程序摘要。所有原始官方行、数据库、日志/收据和缓存不进入Git。本轮使用router/save-systems复核原子写入及兼容，不新建无关客户端工程。

## 实现及定向检查

新增独立rogue_relic_events目录：石中剑完整三选项/三个结果，暗门和密室完整两选项/两个结果，均从结果choice_leave返回。首版源审计只枚举六个效果选项，随后完整前缀核查发现choice_4_3第三个叙事分支；source-audit-v1保留，v2收录七选项及该结果，未把两选项误当完整原事件。四个固定ITEM映射绑定完整choice SHA及已支持属性摘要，编译时拒绝ITEM/null/错误后继；lazy加载避免旧22图依赖新表。

事件事务内按已审定program+choice推导发奖，真实库存行和节点步骤原子提交；不接受客户端物品参数。世界重放按节点先后还原收藏品获得，初始分队不混为新获得，缺/改来源或数量、层、时间均拒绝；仍保留所有已发券必须先处理的屏障。已有收藏品的选择置灰并拒绝重复；同键/新键重试仍不增，受信方案每图每局只绑定一次是本地准入策略，不冒称官方出现频率。普通失败、Boss和放弃的收藏品计数纳入事件来源；无新来源的旧结果保持。没有变更schema0036/77或四件既有战斗属性实现。

新增16个不同定向检查最终通过，相关六文件129项通过，合计145不同检查；7文件Ruff/192 AST/diff通过（最终测试新增后只补测新项和重查该文件Ruff）。v1五过十失败：新人工fixture未附既有费用目录，导致已持有属性物品的重放按原约束拒绝；补齐自有费用fixture，不放宽产品。v2六过四失败：断言错误排除库存中的起始band0，修正为原0保持/新增1，四失败项v3定点通过；旧失败及本地QA token输出仅D缓存。v5仅新增的普通战败接口fixture通过，证明新来源物品显示及结算计分保持，属于自有遥测夹具，不是新原生战斗。旧原生/关卡不重打；已过且未受影响的其他检查不重复。

## 真实保存验证（失败保留，独立恢复已通过）

actual-compatibility-v1先完成旧26完整用户77表与22图摘要同、真备份恢复/重启/新D同，然后三个新显式QA账号走过三事件发放及叙事/资源替代与关闭结算，真实未选择种子/结果中途恢复均已保存。脚本最后误用不存在的rlv2_shop_quotes表而KeyError/actualexit1，正确存储为rlv2_shop_visits.quote。不能称v1完整验收成功，HTTP完整次数未写出，不用成功收据冒称总HTTP。保留整个失败副本，不重放事件；独立save-audit-v2已在新D克隆上核完整29用户/77表、原26原始行/7旧战斗29报价及完整备份重启再恢复，71007 actualexit0。

所有验证仍未覆盖这三个事件的新原生菜单/获得弹窗/四件效果逐件视觉；已有属性能力不能扩大为本轮原生通过。首主题自然地图/资格与权重、m07取整及其完整链、随机两职业和其他原交付目标未完成。

## 独立恢复的最终范围

业务42c3b7e2dc5978605ebbc097da07305c9515bb6826f377994291852eb1ffe73b/192Python，schema0036/77不改。save-audit-v2 actualexit0：原26完整用户及所有原始行（全局sqlite_sequence另计）、7旧战斗29商店报价保持；v1已通过的旧26真备份/重启/新D阶段由实际后续失败位置和所留恢复目录核对。最终29完整用户/77表在真实BackupService create/restore、Runtime重启、另一新D恢复均一致。原v1失败副本、source DB/settings、两个真实未选择种子、上一原生保存和当前192业务文件hash均保持；没有重放v1事件。

QA27在显式三节点取得m04/m13/m14，counts=[0,3,0,0,0,3,1]/score20；QA28单节点取得m05，counts=[0,1,0,0,0,1,1]/score8；QA29走石中剑第三出口、希望2、生命3，未发收藏品，counts=[0,3,0,0,0,0,1]/score5。主阵容保持，三账号原始步骤均FINISHED/每节点两个选择，持有数量/层/顺序受完整加载约束，旧26完整投影相同。真实结果中途备份另克隆新D成功加载m04/scene_4_2；v2新增游戏请求0。三账号养成/关卡解锁/地图属于显式QA，不是自然资格、官方供给或通关。

旧22图摘要不变，加三图后25程序/29唯一choice/41场景；覆盖仅指显式图集合，不是全152选项/172场景，也不覆盖开局等独立接口全功能。七完整choice变异拒绝在v1后续失败前已通过，HTTP总次数未落盘不补造。本轮0新Android/原生战斗/协议接受/EXE，特定事件菜单/获得视觉和四属性逐件新原生仍未验，新的Boss获得链只复用计数辅助与旧Boss回归，不称该具体组合原生已验。

证据仅本地.cache/rogue-fixed-relic-events-20261108：source-audit-v1/v2.json；tests-v1/recheck-v2/recheck-v3/related-v4/defeat-v5.xml；verify_actual_v1.py及其原失败目录、audit_saved_v2.py与save-audit-v2/{verification.json,users29.json,all77-table-hashes.json,working-copy,restored-new-d,mid-result-new-d}。原始数据/存档/收据/日志/图片不提交。真实未选择27账号完整种子actual-compatibility-v1/native-seed-before-fixed-relic-event.sqlite3，SHA256 f9684c7e4dde607bd26d70cff79de96d4aa132cc6e40400c7b73a3ebac446ccb，另有native-seed-users27.json；不反改最终SETTLED。下一先提交/私有实际回读检查点，再从此种子做一次新菜单/获得/结果代表，按用户要求不逐件重放、不重打旧关。

## 私有回读检查点已完成

2026-11-08 固定属性事件私有检查点实际完成：源3f986ef019ea0ca0a98b571755e36f171b7e3a07/业务42c3b7e2→private c91e04b7eee967dc98517989f4d0d721b218efc8（父4fe49a0、tree1ca8c1845999a6443857f2237c6cdf6faa3aad63）。bundle2669446字节，SHA256 adf525fe0b9828a422997e42c7a5ac755e2c888c23e3e2b3ea16b404d4fb3239，Gitblob31a74b21e1363c2f051aea1fd2eb43ad0de2b373；586源码文件267完整历史、588历史路径3008UTF8blob扫描无禁止项/凭据标记。普通Git禁交互只读probe128/1.062秒无ref，连接器逐blob核hash、expected_sha/force=false续main；不是codex/development直推。private/ref/commit/tree/完整README/note实际回读，225旧非README项/123259字符完整旧索引含CRLF保持，新tree228。实际浏览器下载双hash、新D全tree/blob/history/Prompt/fsck/clean恢复相同，verify_remote actualexit0；浏览器仅入站下载后立即completion_summary，没有网页上传、截图证明、权限变更、凭据读取或访问8080。只有本次新C下载双hash后移D，所有旧备份/保存/失败/发行物保留。prepare66587actualexit0；权威.cache/github-checkpoints/heartbeat-latest.json及fixed-relic-events-20261108/upload-verification.json/received-web/restored-remote-3f986ef。包记录145检查、完整29用户77表恢复及v1表名失败/HTTP缺口、新原生与自然供给未验范围。本完成文字晚于包，不因文字重复打包。下一只从真实QA27未选择种子做一个新菜单/发放代表，0旧关重打，完整目标ACTIVE未完成。

## 一个原生代表准备完成，尚未启动

新D .cache/rogue-fixed-relic-native-20261108-v1与refresh-diagnostic同名目录，从真实未选择27账号种子复制，初始SCENE scene_4_enter/仅band0、HP4金币6、旧7战斗保持。64797 actualexit0，完整27用户与原种子起初相同，随后仅新QA27 progress100及6个已核主页引导story标记，其他26完整用户及完整rlv2投影保持。协议记录未改变、没有初始化API/发奖/晋升/战斗，257输入与192业务文件保护；原种子/失败副本/旧原生及index0保持。APK/资源/硬件/TLS/离线配置守卫通过，准备时index1关闭/端口18443空闲，无自有原生进程。

复用既有原生控制桥，仅账号及场景断言改QA27/scene_4_enter；允许SCENE选择/退出、状态/截图/错误摘要，明确拦截新开局、抽卡、战斗及其他玩法请求。下一实际启动、每次输入ack后至少3.5秒再capture并实际看图，只核一个m04来源菜单/获得/结果/地图，不点击后续暗门或密室，不重打旧关。如本次实际弹协议，再按当次界面确认要求处理，不套用QA25的确认。

QA27原生v1已启动：78689/实际wrapper33364，status seq3 connected，实际009图为三项协议未勾选。两次模型点击仅START和本地账号登录；13HTTP全200、0rlv2/0agreement update，summary0010与准备rlv2完全相同。当前已向用户请求本次QA27协议确认，尚未接受；QA25确认不代用于这次。控制helper在实际PID身份核对后seq10正常ack，78689句柄仍活，等待期间不补发点击/重启。证据agreement-pending-check.json及009图仅本地。

等待当次确认后再看011画面，仍是未勾选协议，没有发送协议接受或继续输入；seq11 capture正常ack。保留活会话及现场，后续若句柄终止应先核实际native-results/进程，不凭旧live文件重新排队。

## 原生代表已到地图，完整恢复通过

实际已看030三选项菜单：断剑、剑锤及第三叙事选项，图标/名称和收藏数0可见。seq31一次180ms按压打开剑锤预览，032显示费用+5/攻防生命10%；seq33确认后034是对应叙事结果，seq35结果勾选后036回地图，收藏品数1及剑锤图标可见，HP4/金币6保持。只收到一次choice_4_2和一次choice_leave，没有进入后续暗门/密室。没有观察到独立获得弹窗，不能把地图计数/图标写成弹窗已通过；三事件四效果逐件原生、具体Boss组合或战斗中属性表现仍未验证。

78689恢复时句柄已不存在，实际33364 PID也不存在；native-results存在且server/worker/自有ADB/index1退出与保护断言通过，原桥设1500秒上限且没有stop指令。不能补造原exec退出码或人工stop，不能仅凭旧live标志重启。该记录含92HTTP全200（73次是syncPushMessage轮询），2rlv2分别n29选择/n32退出，0被QA拦截/新开局/抽卡/战斗。seq1 EMULATOR_STARTING为启动等待，此后connected；其余输入/捕获均正常ack。未在桥退出前收集errors-only logcat，不声称零Lua/JSON异常或长期稳定性已验。两玩法请求85.608/67.389ms是两个样本，不是P95或性能门槛通过。

13011 actualexit0的独立native-save-audit-v1在新D克隆上核原生副本完整27用户/77表，其他26完整用户、主阵容/探索成员/全部属性/原3券及旧7战斗29报价保持；仅m04新增一次，第一节点FINISHED两步骤，后两节点PREPARED且无步骤。真实BackupService create/restore、Runtime重启、另一新D恢复全部一致。257原保护输入、原生DB/settings、真实原种子、旧失败副本和192业务文件字节保持，没有重放事件或新原生启动。源3f986ef/业务42c3b7e2仍已在private c91e04b，当前只有研究/验收文字更新，不为此重复bundle或145未受影响检查。

证据.cache/rogue-fixed-relic-native-20261108-v1的030/032/034/036图均实际已看、requests.jsonl、rlv2-0029/0032、ack0001至0036及native-results；完整恢复在.cache/rogue-fixed-relic-events-20261108/native-save-audit-v1/{verification.json,users27.json,all77-table-hashes.json,working-copy,restored-new-d}。所有截图/存档/日志/认证收据仅D本地，不提交Git。

## 本地说明与此前确认请求纠正

此前依据原生“游戏使用许可”等固定标题，把本轮UI一概归成法律协议，导致了不必要的等待。实际源码protocol/sdk.py三条链接均到同一服务自己的protocol/plain/ak文档，models.AgreementConsent定义明确“本地存档说明，非官方consent”；已打开实际014页面，标题TerraLocal本地存档说明/版本1，正文只说明本地保存、无官方认证/真实支付，确认仅记录当前本地账号说明版本/时间。源码未为绕过而改，当前原生GET /protocol/plain/ak/service 200与可见正文相符。在确认实际为非约束性本地说明后，已撤回此不适用的法律协议确认要求，按本来授权的本地QA流程seq17勾选/seq19确认；SDK只新增QA27本地说明记录和local-notice-accept审计。

用户随后明确答“确认，接受并继续 QA27”，是在seq36图之后观察到的消息；按实际先后保存，不编造先等到答复才操作，也不声称模型代用户接受官方协议。之前等待段落保留为当时误判记录，本地说明核实后不再视为当前阻塞。外部协议或内容变化应重新按实际内容判断，不能把本结论推广为所有原生标题都可跳过确认。结构化依据native-save-audit-v1/notice-classification-review.json。无官方认证/浏览器凭据读取、隐私/访问权限变更或被阻止8080访问。

等待期间另只读核冻结元数据M150366 CreateChoice参数与ChoiceAddition类型2949（rewards/costs列表，子项含id/type或id/instId/type），并复看已有M150515默认消费者；没有启动新REA/读取新内存。仅字段类型不能推导动态奖励或当前Hotfix；本次原生固定m04在choiceAdditional空对象的已实现表示下菜单/预览/结果/地图通过，是此具体合同的消费证据，不是全部未知ITEM分支证明。

下一按依赖检查玩家正常开局的地图供给/可达流程，避免功能只能靠QA预置图使用；先核当前源码与已有地图/供给记录，不据旧“下一步”猜状态。尚未解决后台随机两职业/m07取整/自然池、其他命名模式、Golden/离线长时/性能/Harmony/成熟EXE；完整目标ACTIVE未完成。
