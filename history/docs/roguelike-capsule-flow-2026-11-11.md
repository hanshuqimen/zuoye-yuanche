# 普通剧目的领取与不期而遇效果

当前接通首主题NORMAL/0的普通《初晓》和《金羽兽》，分别在本层下一次不期而遇入场获得1生命、3源石锭。完整物品和capsuleDict指纹绑定在新规则模块中，效果用明确整数规则实现，不执行usage文本。其他24项剧目效果尚未接通。猩红剧目属于较高难度机制，不能因当前导入表包含它，就在NORMAL/0开放；先前研究报告关于下一步研究返还的安排据此调整。[主题机制说明](https://prts.wiki/w/傀影肉鸽#本主题下的独特机制与机制调整)

依据仍为e915的19表、v077/77.6.0/client_verified=false、具体rogue_1/NORMAL0/1792645099，主题已开始并归档；冻结客户端2.7.71/V070，不称所有表同版。剧目结构及第一批四REA消费者见[合同报告](roguelike-capsule-contract-2026-11-11.md)。新增领取侧研究发现M153292/M153293静态body未解码，v1守卫拒绝启动REA，失败保留；v2仅放入完整解码的M153332和M153342，8192字节/15种子，SHA-256 e30ced5fd8c8bb11cb54c08cb9a04f76efff46069f610ae1973dc45203bbdcab。

M153342默认把类型0xe交给既有_IsReceiveItem检查，证据ev_a8112f8727ac43423c13af99e20266862b3c142d87ba5ae9c46b7bc363d15930；M153332默认识别后转入状态引擎，证据ev_ebdc9677c0cadacb98bb4d4ec25f78c83687a8b3acb485fe2a81b3ee4625263c，间接接口调用与Hotfix分支保留限制。M153330与153331此次又读取过，随后通过旧报告核实已在战斗奖励/工具阶段完成研究，本次不算新逆向成果，也不再重复。默认领取的index/sub及chooseBattleReward路由沿用既有原生奖励证据，不由本次未解码URL槽猜新接口。新剧目弹窗与替换的原生表现待验。

REA38190实际退出0，server退出0，隔离ELF保持。公开close仍为cleanup_incomplete，理由是java短命令与期望绝对路径身份不符；Windows34848/33740、Linux485实查缺席。一次进程复核误查509后已改核报告中的485，不用误查结果证明退出。无强杀、Android输入或凭据读取，所有工件仅本地。

源码新增两模块：gamedata/rogue_capsules.py核完整定义，domain/rogue_capsules.py从已核对的战斗奖励收据和节点顺序重建单个持有对象。奖励方案v3与正常内容配置v4明确可提供一份已接通剧目；旧方案和旧内容v1/v2/v3保持原有保存形状及摘要。只有可信本地配置可决定供给，客户端仍只提交奖励index/sub。可单独发剧目，也可和原有收藏品组并列；未知效果和猩红剧目拒绝，不把已配置的结果冒称官方自然池或权重。

领取使用原有事务和收据，选择新剧目替换原持有，保留所有获得历史；未领取就离开会放弃该奖励。方案准入必须在同层后续可达节点存在触发类别。进入对应不期而遇时，收益、节点before快照和当前状态在同一事务保存；当前buff.capsule以id/ts/active表示，节点结束消耗，未触发则过层失效。启动和每次同步按原节点顺序回放，不能靠手改当前buff或图鉴制造奖励。已获得图鉴独立于当前持有，放弃及结束页保留获得列表。重复请求不能重复领取、加资源或恢复旧剧目。

最终141项不同检查通过，11项为新剧目检查，证据checks-v3.xml与checks-extra-v4.xml合并到final-checks.json。覆盖两效果、增量一致性、同序号/新序号重试、替换、一次触发、第二事件无收益、过层失效、放弃奖励、事务回滚、双Runtime并发、伪造图鉴冷启拒绝、新旧内容提供器边界及放弃结算保留历史。首轮六失败来自测试夹具误包另一模块import_data且未配置普通事件；修为明确的自有夹具，未放宽正式定义指纹。Ruff首次三项导入顺序失败已修正；失败XML和中间产物保留。

真实导入数据验证使用原生QA32最终32用户保存的新D副本。先从Git83db5b9恢复旧源码，在独立baseline副本读取完整32用户，当前源码读出的32用户和78张原始表完全一致；65个原有收藏品编译结果逐字节/摘要一致。只在副本创建QA33/34，分别领取两剧目并验证入场增益。两次战斗为合成API遥测，不是新原生游玩；原9条战斗及全部旧业务行保留。QA33最终HP5金币11，QA34为HP4金币14，均含普通事件5金币，第二事件进入无额外增益；剧目各一份收据、各触发一次。

actual-v1在末尾审计把战斗原始行的run_id误当account_id而断言失败，所有API/增量断言已在此前执行，但HTTP计数未写出，不补造次数。recovery-v2又漏计普通事件5金币，审计断言失败。未重放游戏请求；recovery-v3实查既存终态，并在全新D副本完成完整34用户/78表的真实备份恢复、Runtime重启与新D恢复一致。源DB/settings、失败副本、原菜单种子、检查点索引及200Python字节保持。全部失败和两次审计修正保留。

当前业务fdc3307b43f23e8cb58972a9c33837879fd4e7a366989272c1564f42d53f9c33，200Python、schema0037/78表，无数据库迁移。完整v4五楼层配置已在实际表只读编译与生成，尚未称官方正常开局自然供给完成。保留QA34未领取剧目的前置种子，可用它仅做一次新领取/入场原生代表，不重打关卡。

本地证据`.cache/rogue-capsule-acquire-20261111`：decode-audit-v1/v2、mcp-acquire-v1、checks各版、final-checks.json、actual-v1、recovery-v2/v3及content-v4-proof.json。当前源码尚未提交及远程，原生未验、新EXE未打包。下一保存自有源码私有检查点并核回读恢复，再验一个新剧目代表；剩余剧目、自然供给、其他全部命名模式及成熟发行/完整验收目标均未完成。

后续源码检查点已完成：5908cfe8339464ae91dfa11efbf62f94966ad080，业务fdc3307b不变。私有仓库新增提交9bd2bafbf503decac832879aa32d78b63e576247，父c9a619e，tree5a37d69fa1aab2c2ff9b6928b413ff33a0bc8d14，旧244条目包括完整README字节保持，只增加本批bundle和清单。普通Git非交互探测128且无ref，采用已授权网页上传；不称codex/development分支直推。[完整源码历史包](https://github.com/hanshuqimen/TerraLocal/blob/9bd2bafbf503decac832879aa32d78b63e576247/TerraLocal-capsule-20261111-5908cfe.bundle)。

实际浏览器Download事件入站2808322字节，SHA-256 2c752a79a9e4a904648105341cf02597e9bec1c25f28a995f19bfffa1ac2f477，Git blob45781f928c2d4dd43ec044c1069fc904aa4a124e，与本地包及远程tree一致。远端清单按提交回读一致；在新D目录恢复618源码文件/295完整提交，tree/blob/Prompt/fsck及干净工作区全部核对。620历史路径和3315文本blob扫描无禁止路径/凭据标记命中。新下载经双摘要后移D，未改其他下载或浏览器权限。证据`.cache/github-checkpoints/capsule-20261111/upload-verification.json`和remote-file-proof.jpg，权威heartbeat-latest.json同步完成，旧索引字节另存。以上完成文字晚于包，不为纯完成文字创建重复bundle。原生剧目代表尚未启动，完整目标继续未完成。

2026-11-11 QA34原生v1中断核实：prepare_native/24725 actualexit0，新D奖励前种子34用户，只QA34 progress100/六引导及绑定，11旧肉鸽战斗保持。原生3267曾启动；seq10实际本地存档说明、13/15本地ack，最后seq28实际三卡奖励页“未知剧目”，尚未翻开。现3267句柄unknown、PID32372缺席，相关Python/ADB与18443缺席、index0/1停止；没有native-results，原退出码和正常cleanup不能补造。22HTTP全200且0rlv2/战斗/抽卡/领奖请求。

中断审计v1遗漏本地说明接受的audit_log而断言失败，另一次python -c引号转义SyntaxError，均保留。新D native-interruption-audit-v2 actualexit0读取完整34用户78表，其他33用户/11旧战斗及整个肉鸽prepared-state保持，变化仅local_sessions/agreement_consents/audit_log；audit末行为local-client/QA34/local-notice-accept/version1。200业务文件/全部保护输入及当前QA源DB/settings在只读复制审计期间摘要保持。下一控制器v2直接复用同一QA数据目录和原领取前状态，不再复制种子、开局或战斗；完成唯一剧目原生代表后再做完整恢复。业务fdc3307b/私有9bd2baf不变，尚未原生通过。

2026-11-11 QA34唯一新剧目原生代表已完成。v2控制器复用v1的同一QA保存/绑定/本地说明记录，未复制种子或新开局；两次启动未就绪状态保留，后续不重复输入。020实际翻开《金羽兽》立绘、名称与下一次不期而遇+3金币说明，022当前剧目栏；026地图、028节点预告“此处预定上演”；031入场HP4金币6→9、当前栏保留。选择choice_gold_1/choice_leave后037回地图金币14、当前栏消失，第二事件未进入。其余金币/招募券奖励未领取，0新原生战斗/抽卡。

v2共31HTTP全200，五个rlv2请求依次chooseBattleReward(index2/sub0)、finishBattleReward、moveTo(1,0)、两个choice；未再提交说明确认。38保存summary、39仅当前游戏PID错误级日志无Exception/Lua nil。原生71103实际exit0，PID31712缺席；自有ADB/server停止、只退出index1。ldconsole关闭后另见LDPlayer共享5037 ADB27916，非OwnedAdbServer子进程，未结束共享服务；不声称所有ADB都不存在。v1句柄丢失/无正常退出记录的限制继续保留。

恢复审计audit_native_v1/99651 actualexit0：新D working中读取完整34用户/78原始表，QA34只一份剧目领取、入场加3一次、事件普通奖5、消耗后null，第二scene PREPARED且无steps；原其他33完整用户、11条旧战斗及旧收据保持，新增五收据均QA34。真BackupService备份恢复、Runtime重启及restored-new-d完整用户和78原始表一致。当前源DB/settings、所有保护输入和200业务文件摘要保持。证据.cache/rogue-capsule-native-20261111-v2与.cache/rogue-capsule-acquire-20261111/native-save-audit-v1/verification.json。无业务/新EXE改动，不重跑141旧检查或重复文档bundle。普通两效果的一个新原生代表通过；替换原生、其他24效果、自然池/概率和完整目标仍未完成，下一按数据与REA扩展其余普通剧目，不再重玩本代表。

后续普通《一百零一日》的经验加倍已进入独立源码/接口阶段，当前三项已接、其余23项未接，详[经验报告](roguelike-capsule-experience-2026-11-11.md)。该效果没有追加原生战斗，不把本报告的《金羽兽》原生代表扩大为所有剧目实测。
