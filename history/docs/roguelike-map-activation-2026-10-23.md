# 地图节点键纠正与初始化收尾（2026-10-23）

继续完整目标，不恢复剿灭/重复同关。前一阶段地图准备存档已完成，本阶段接真实初始化收尾，但尚未冒称完整首层/玩法通过。

## 依据及纠正

REA对冻结2.7.71/build190 ELF的M33652 GetNodeKeyByPos(depth,index)/0x44f4108取得完整140字节与默认路径：index+depth*1000，再转字符串。提供器exit0，观察ev_fc5bdb0b17ec4b6dc634598505a0a9a0d84f7e16b25c258b02509aed07b6470c。Hotfix存在时委托另一路径，未还原，不把默认路径扩大为全部动态行为。

旧*100社区兼容候选有确切反例，因此撤回。新生成策略v2用1000；旧v1保留原策略/种子/方案指纹和*100图JSON，读取按旧codec校验，再只读组装native1000，不重抽/回写原图。不是通过覆盖旧失败来假称一直正确。

M33632 GeneCommonDungeonZoneWithoutReachability和M33630 GetDefaultCurrentDungeonZone都完整线性解码且REA exit0，但分析遇跨方法/PIC/unreachable警告，保留局部有效观察，不宣称完整地图渲染函数或服务器概率被逆向。M33645 CanNextStepNode仅静态准备；默认静态分支检查WAIT_MOVE值3及未进入任何深度时的第一列。旧GetCurrentIndex默认在position为null时返回-1，不造负数地图节点。

[玩家实测汇总](https://prts.wiki/w/傀影与猩红孤钻#区域)记载首层四列、起点战斗、次列事件分支及商店出口；[同页遭遇记录](https://prts.wiki/w/傀影与猩红孤钻#作战关卡)包括首层五种普通关。对应冻结表逐名核对为与虫为伴、驯兽小屋、礼炮小队、意外、死斗。它们支持本次具体QA图，不证明官方随机权重、全部第三列条件或所有难度规则。第三列及连线概率保留明确QA方案，未变成产品默认。

## 源码行为

finishEvent严格空请求，复用认证/账号隔离/幂等收据/差量/事务。只有INIT_RECRUIT且三券DONE、已有保存且校验通过的zone_1图时，原子保存最后初始事件完成时间、地图activated_at及Run MAP_READY；同步投影WAIT_MOVE、cursor zone0/position null和实际完整map.zones[0]。准备图不等于完成事件。重复原序号回放收据，新序号只复核已有地图，不重抽、不进入下一层、不发奖。

没有准备方案时503且不完成事件；错误区域501；未处理完券或其他步骤409。未猜最低干员要求或给全部放弃分支冒充官方结论。普通钱包/仓库/干员与初始招募结果保持，节点移动/事件/战斗仍未接通，不给未知按钮万能成功。

schema0022_rogue_map_activation仍68表，新增activated_at并扩展Run约束。0021/0020/0019父表重建前只在专用迁移连接、事务外暂关FK，完整BEGIN IMMEDIATE事务串行重建，校验全部引用；finally恢复FK。正常成功与失败回滚均验证子记录/版本/索引保持；不使用中途开启FK、级联删除子表或覆盖旧DB来迁移。备份候选也先验证绑定/激活时间/事件状态，损坏拒绝后才会触及活动数据。

## 检查与原生准备

首轮113通过/1失败，原因是新增回滚用例传空字符串UID而被认证拒绝；修为None后才实际覆盖事务。后轮142通过/1旧占位预期失败（28.83秒）；该反例原来要求finishEvent无论payload均501，而新接口按冻结空请求合同拒绝额外字段422、无Run409，修正后单项1.13秒通过。活动地图备份恢复扩展单项0.91秒通过；Ruff零、一项既有FastAPI/httpx提示。不把分组相加或称新全量通过。

覆盖v1原图只读兼容、严格native键/方案、重复/并发收尾、差量一致、事务收据回滚、地图事件/时间/区域/删除损坏、旧schema行/索引/FK守卫、迁移中途失败回滚，以及重启/活动备份恢复。

实际冻结19表的旧schema0021地图在新D目录迁移至0022：旧图JSON及旧行（版本/新增NULL列除外）保持，原DB字节未改，读出native1000键。v8由v7停机副本准备，原同一Run/两名已招干员/全资源保持，只改迁移版本和新增QA图。26输入受保护；未启动原生，不记地图通过。

业务63a214d2f70cc3d6f635d5461ebef351235e0ff3d411d1055bc31f3d8ad42774。证据.cache/rogue-map-activation-20261023/{validation,actual-legacy-verification}.json、rea-map和检查输出；.cache/rogue-native-20261023-v8/prepared.json及qa-map-plan.json。下一步只验证一次进入古堡/地图展示，不移动/开战或重复初始化。完整主题、官方地图分布、节点/战斗/奖励/结局、其他指定玩法与成熟EXE目标保持。

## 2026-10-23 v8停机及v9恢复准备

2026-10-23 v8来源0975c4b/业务63a214d2，原生finishEvent已实际200并保存MAP_READY/最后初始事件与activated_at，169请求全200，唯一rlv2路由为finishEvent；希望3/HP4/金币6/两干员保持、战斗0。最后screen-08只捕到黑色转场，地图画面尚未验证。辅助before/result相差1800.49秒且脚本上限1800，生成正常清理报告/56其他账号表与26输入保持；实际源PID33316和执行句柄已不存在、18443关闭、index1退出，不能因为旧live-process继续输入。后续截图守卫拒绝未发送点击；旧现场保留。新v9全新D副本68表初始完全一致/29输入受保护，无新夹具，只恢复MAP_READY捕地图，不重复finishEvent/初始化/旧关卡；尚未启动。

证据.cache/rogue-native-20261023-v8/{native-results,reviewed-results,rlv2-0018}.json、screen-08-enter-map.png；v9 prepared.json。全目标保持，QA图概率/首层供给/节点/战斗未完成，未打包新EXE。

## 2026-10-23 首层编号纠正

2026-10-23 v9真实地图黑屏反例：24请求200/无rlv2调用，只local_sessions变化，正常清理/56其他账号表及29输入保持。当前进程Error级严格脱敏诊断取得两次ArgumentNullException、Parameter name:key，站点含RenderBackground/RL01MainTransitionView.Render；未保存原日志。REA M33629/0x44f1a04默认路径确认cursor.zone==0生成空初始化模型，非零才按编号取map.zones；撤回旧收尾cursor0/map0投影，真实首层改1。持久化Run/图/收据不变，旧收尾收据只读改map1/cursor1并删除旧0键，防止重试重现黑屏，不重新发奖。94相关检查29.98秒/Ruff零/1既有警告；实际v10完整投影首层1、1份旧收据转换、68表行/32输入保持。业务176b864786dd90d11bcec737c89f3adaeaeb8518204634da7eda836f871c09b6，schema0022/68表不变，无新EXE；v10副本恢复同一MAP_READY，只验证地图，尚未启动。

M33629提供器exit0/600字节完整，ev_88882407204084d03198b6e0f1faaa3ad21d198a9bf84ce4633cda58e34d4311；Hotfix路径有截断警告，默认零编号分支有静态完整指令和可读伪代码共同支持。此前关于cursor zone0/地图key0是有效入口的推断已被原生反例否定，旧成功传输/源码检查不证明地图可用。证据v9 reviewed-results.json/errors-0012.json/sanitized-null-parameter.json/screen-06-map.png、.cache/rogue-map-activation-20261023/rea-current-zone与tests-zone-index.txt、v10 zone-index-wire-probe.json。全文目标/节点/战斗/实际随机规则仍未完成。

## 2026-10-23 地图显示原生通过

2026-10-23 v10来源22beb2e/业务176b8647，原生地图显示通过：正常迷雾歧途启程转场、起点意外/两条不期而遇/古堡馈赠/诡意行商与连线、横向滚动实际可见；HP4/希望3/金币6/两干员保持。20请求200/无rlv2请求，仅local_sessions变化，当前游戏进程Error计数为空。未重复finishEvent/招募/初始化，没有MoveTo或战斗；只证明四列QA图展示，未证明官方随机分布/节点玩法。正常exit0及所属服务/ADB/index1关闭、56其他账号表与32输入保持；新D Runtime重开68表/完整rlv2与最后快照相等、备份恢复68表相等、原DB字节保持。v8超时未捕图和v9黑屏失败保留，无新EXE。下一步MoveTo/节点pending/编队与肉鸽战斗，完整目标保持。

证据.cache/rogue-native-20261023-v10/reviewed-results.json，screen-08-map转场、screen-09-map起点/分支、screen-10-map-end馈赠/商店，errors-0019空诊断、summary-0020与reopen-verification；只有本次实际范围。新检查点索引.cache/github-checkpoints/rogue-map-activation-20261023/upload-verification.json，回读/新D恢复前不记远程完成。
