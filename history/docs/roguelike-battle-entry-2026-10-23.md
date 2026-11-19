# 肉鸽战斗入口与节点分支（2026-10-23）

继续完整目标，前阶段地图原生显示已通过，不重测旧关卡或剿灭。本阶段先确定实际客户端调用分支，再实现战斗/非战斗节点，不能从相似接口猜一个万能成功流程。

冻结CN2.7.71/build190 metadata：RoguelikeMoveToRequest仅to，响应无声明字段。RoguelikeStartBattleRequest（M类型2128）有to、stageId、squad；squad类型CommonStartBattleRequest.SquadModel。RoguelikeFinishBattleRequest有battleLog字符串及RoguelikeOutput结构，不能直接当普通quest/battleFinish的相同封包。

RoguelikeSquadState._StartBattle M155625/0x3f50640有2472字节，但磁盘受保护零线性解码；提供器守卫拒绝，未启动REA。下一步仅对测试实例当前包读取0x3f50000文件映射代码页（4KiB），验证硬件/APK/ELF/映射/8秒命令限制，不读堆、玩家对象或认证。当前仅静态失败证据，不假称方法完整。

新v11由停止v10完整克隆68表，无新夹具或奖励，35原输入受保护。准备一次已有地图上的战斗节点预览观察；禁止battleStart，不重复初始化/finishEvent/关卡游玩。辅助只记rlv2字段名、合法坐标、关卡标识和原有白名单字段，认证/原始日志不记录。原生尚未启动，最终接口行为和战斗流程待证据。

本地证据.cache/rogue-node-flow-20261023与.cache/rogue-native-20261023-v11；当前业务176b864786dd90d11bcec737c89f3adaeaeb8518204634da7eda836f871c09b6，无新业务实现/EXE。完整主题、地图供给/概率、节点/战斗/奖励/结局及所有指定游戏系统和完整交付门槛继续未完成。


## v11完成与调用分支纠正

此前“尚未启动/磁盘零解码”的段落保留为准备历史。v11来源386691b、业务176b8647实际完成：21请求全部200、rlv2请求0，点击起点“意外”显示关卡预览，ENTER打开两名局内干员的编队（阿米娅lv1、预备干员-重装lv55，2/6），未点击StartAction。预览与编队均为客户端本地操作，不能推断战斗节点先调用MoveTo。无关卡游玩、无新战斗/奖励；仅local_sessions变化，56其他账号表/35输入保持，正常停止exit0，所属服务/ADB/index1关闭。证据`.cache/rogue-native-20261023-v11/reviewed-results.json`、screen-08-node.png、screen-09-formation.png、summary-0021.json。此轮没有另做v11 Runtime重开证明，不冒用v10的重开证据。

在冻结包/硬件/ELF映射与8秒命令守卫下，仅读取0x3f50000文件映射代码页4KiB，没有读取堆、玩家对象、官方认证或日志。页SHA256 1b9bef29963f5a4c0c8c9bb83ec1552436105b4489b6b6381147bbca133774d4。载入后的M155625（0x3f50640，2472字节）完整解码，方法体SHA256 331c33177d904c7f564e8c8c0dc369c0897610b906edf0c0e5d185a705121cb1。REA提供器正常exit0，观察ev_a4ed5efe474beb3713527ac34a5f6dd76fa207f5d7e4ebba4c00fd25f018af68；存在类型传播未收敛/全局变量重叠警告，不据此声称整个客户端逆向完成。默认路径构造可空目标、关卡及只写slots的SquadModel，再调用公共战斗管线0x44ec27c；跨下一页的闭包未读取/未逆向。磁盘保护失败原证据继续保留。

请求继承补证：StartBattleRequest父类object，字段to/stageId/squad；FinishBattleRequest继承CommonFinishBattleRequest，因此同时包含基类data/battleData与自身battleLog/rlv2Data；RoguelikeOutput声明只有battleSnapshot。不能把结算当仅两个字段或与普通quest封包完全相同。索引的route_literals旧白名单未包含rlv2；扩展提取仅找到moveTo等字符串，没有找到战斗完整路由。源码接入/rlv2/battleStart是待原生核对的兼容候选，不把路由命名推断当已观察请求。

## 独立开战源码与检查

新增rlv2_battles，schema0023_rogue_battle_start/69表：绑定账号/Run/本地游戏登录/数据/策略/首节点/关卡、随机种子、不可变局内编队、请求摘要和开始时间。只接受已激活地图的可达首战斗节点；NORMAL/ELITE/BOSS使用同一目标校验并要求匹配已保存节点，不把全部候选铺进实际第一层。严格检查局内所有权、重复干员、容量、技能、模组、空位和额外字段；不修改永久干员、扣普通理智、发普通关卡进度或奖励。

同键重试由既有事务收据返回；同登录同目标/编队的新序号复用原battleId与种子，冲突请求拒绝。与普通/剿灭战斗双向互斥；旧登录不能新开战，换登录后旧战斗保持并明确501拒绝未接通的原生续接。外层失败连同战斗/收据回滚。主动放弃探索只关闭独立记录，无结算奖励；时间回拨时保留开始边界。sync输出PENDING、目标坐标及BattleContent；state=0等默认字段仍是未验证候选。

启动/备份恢复在写入/迁移前只读核对目标/关卡/编队/会话/数据/策略/摘要/时间及跨模式冲突，损坏候选不改当前存档。0022升级仅新增空表；0021/20/19/18原迁移路径同步接入该表，旧回滚/子记录/FK检查更新。

实际检查：首轮29通过/3测试错误（表名、调用签名、故意损坏被CHECK提前拦截），修正用例；相关组107通过/1迁移测试未排除新增空表，40.58秒；修正后最终92项通过33.02秒/Ruff零/1既有Starlette警告。最终组包括34项新开战用例、已失败的0020迁移用例及普通/剿灭开战相关检查，与前组重叠，不相加冒称全量。未重测无影响的原生关卡。日志`.cache/rogue-node-flow-20261023/battle-start-tests-{first,related,final}.txt`及battle-start-ruff.txt保留。

冻结e915675d实际19表：新D目录migration-and-data-review复制原v11，68旧表行（除版本）保持，升69表/无新战斗；完整rlv2重开相等，真实备份恢复69表相等、原DB/settings字节保持。对90个关卡逐项核对目录分类与精确节点绑定：普通45/紧急36/Boss9，使用每条独立人工图验证绑定；这不证明楼层准入、官方概率、奖励或90关原生通过。证据battle-start-data-validation.json及battle-start-validation.json，业务874288e8856bf4b06950a7e0d86cd36ec5170bba8fd7a1cb5a7f7c8aa592ac07。

## 当前缺口与下一步

未进行肉鸽原生StartBattle/FinishBattle；没有玩首关。精确开战路由与完整原生请求、BattleContent状态及种子消费、结算封包/奖励/后续节点/主题结局、正式地图方案和概率仍未接通；不能把开战基础设施说成完整主题或成熟交付。下一步用独立副本和QA拦截核对一次真实开战请求（不启动战斗、不改存档），随后接结算与节点推进，仅在必要代表流程中游玩。v35剿灭保留不恢复，全交付目标保持，无新EXE。


## v12实际请求纠正（当前）

上段“精确路由待核对”现由实际请求解决；候选实现2327c7e/874288e8不是最终兼容合同。本次从v11停止存档在新D目录复制68表，升级69表且旧行除版本保持，没有新夹具或重复初始化。index1恢复同一地图/编队，点击StartAction一次，实际发出**POST /rlv2/moveAndBattleStart**，字段严格为to/stageId/squad；to={x:0,y:0}、stageId=ro1_n_1_4；squad的squadId/name均null，两槽字段charInstId/skillIndex/currentEquip，实际技能编号分别0与**-1**，currentEquip均null。没有先MoveTo。

此前QA白名单只拦battleStart/startBattle，**没有命中实际新路由**；由现有产品未知路由处理器返回501，原生显示“错误号501”提示。不是QA409、不是开战成功，未重复点击或重连。未创建任何普通/肉鸽战斗、奖励或进度。不能将这次501截图当成功消费证据。修正源码为观察到的moveAndBattleStart；无技能干员只接受-1，拒绝旧猜测0，普通已解锁技能仍按0起始下标；未保留错误候选路由作为虚假可用接口。

v12实际28请求（27HTTP200/1HTTP501）、仅local_sessions变化，57其他账号表与38受保护输入保持；Error类型计数为空，不把错误对话框抹去。辅助seq5第一次tap误用x/y而应xy，KeyError发生在发送Android命令前；确认截图仍停登录页后才正确发送，失败记录保留。正常停止/执行句柄exit0，PID23172实际不存在，18443关闭，所属ADB/index1关闭。证据.cache/rogue-native-20261023-v12/{reviewed-results.json,requests.jsonl,screen-14-blocked.png,summary-0028.json}。

修正后的35项原专项加1项按原生形状重建的用例，共**36通过21.16秒/Ruff零/1既有警告**；不重测无影响的普通/剿灭场景。新增用例只换人工关卡ID，不含客户端资源/认证。新D native-v12-reopen-review重开69表所有行保持，完整rlv2与最后summary-0028相等，实际备份恢复69表相等；原v12 DB/settings字节保持。未重复90条目录扫描，其上一业务874288e8的分类/节点校验模块未受这两处修正影响。当前业务51a5c645133d09fd9f4d6160e927ee606d46107b70fd30369215bdc213bfe5c5，schema0023不变。证据battle-start-native-contract-validation.json、battle-start-v12-reopen-validation.json、battle-start-tests-native-contract.txt。未生成新EXE。

当前剩余：原生开战成功响应/状态字段消费、结算data/battleData/battleLog/battleSnapshot的完整校验/奖励/后续节点/正式地图供给与概率/主题结局及全部完整交付门槛。下一步先结算合同与节点规则，避免重复同关；v35仍保留不恢复。
