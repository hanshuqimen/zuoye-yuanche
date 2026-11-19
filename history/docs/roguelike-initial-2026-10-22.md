# 傀影普通0开局与初始选择（2026-10-22）

后续纠正：本报告记录的“结束水位”冷却策略已被长探索反例否定并撤回，当前从开局计时；普通招募已进入后续实现阶段。历史内容保留，当前事实见[招募与冷却纠正报告](roguelike-recruit-2026-10-22.md)。

本轮继续完整集成战略目标，不重复游玩旧关、不恢复剿灭v35。推进的是傀影普通难度0的初始化；第三步实际招募、地图和战斗还未接通，不能称完整主题可玩。

## 当前实现

新增独立rlv2_runs、rlv2_events、rlv2_relics、rlv2_tickets，源码schema0019_rogue_initial_runs/新QA65表。活动探索按账号使用部分唯一索引（ended_at IS NULL），同时保留已放弃记录和事件步骤。Run绑定数据指纹/策略；数值、阶段、事件种类/顺序/完整内容、藏品和待激活券之间一致性校验，不把整个current JSON当存档。

接入 `/rlv2/createGame`、`chooseInitialRelic`、`chooseInitialRecruitSet`、`giveUpGame`，复用认证、幂等、差量及事务。创建只支持rogue_1/NORMAL/0，无预设/活动；EASY的专用模式藏品、其他难度、月度/挑战和其他主题没有默认转普通模式。必须已经通过GameData.constant给出的开放关卡；当前采用PASS（至少1星）作为本地通关判定，未声称已逐项还原官方服务端资格。已有探索/普通战斗时不新建第二场，不扣理智或普通资源。

初始HP/希望/金币/编制读取精确init配置：实际冻结普通0为4/6/6/6，hp.max=0保留数据的initialMaxHp=0，不猜成4，也不施加current<=max。指挥最高等级读取playerLevelTable（实际10），冷却读取ordiModeReOpenCoolDown（60秒）。初始化保持INIT，地图为空且没有战斗；不伪造通关/结算/关卡奖励。

初始分队只提供该基础配置中唯一没有解锁条件说明的分队（实际指挥分队），选项键为"0"，服务端按已经提供的选项验证。藏品写入独立Run背包一次；每战临时生命+4的效果保留为藏品定义，未错误变成永久生命+4。条件分队的资格尚未实现。

三种基础招募组合由冻结中文说明明确列出的职业配方适配，并按recruitTickets的职业/ALL范围、extraEliteNum=0和无extraFreeRarity，找到唯一普通券；不按后缀猜券、不混入高级或猩红券：

| 组合 | 职业 |
|---|---|
| 先手必胜 | 先锋、狙击、特种 |
| 稳扎稳打 | 重装、术师、狙击 |
| 取长补短 | 近卫、辅助、医疗 |

表中recruitGrps只有文字说明，没有机器可读的完整配方；这三条是明确记录的规则适配。随心所欲/挑战组合及保证临时招募尚未实现，不用普通组合替代。选好组合只生成3张CREATE态券并进入GAME_INIT_RECRUIT，未招募干员、扣希望、产生免费临时干员或假完成第三步。实际chooseInitialRecruit/激活/角色选择仍明确未实现。

基础可用性是只读投影：首主题NORMAL/0、唯一无条件分队、3基础组合显示available/unattained状态1；不写入USED/ATTAINED、不推断高难度或条件解锁，不改变数据库中的收藏/余额/历史。这是明确的本地基础可用性策略，尚未取得原生界面或官方新号快照证明其完全等价。存储策略格式仍为v1；旧outer行不因投影而改写。

放弃仅处理当前已经接纳的初始化阶段，保留Run/已完成步骤、清空当前探索视图，不发任何结算奖励。重开冷却用有效结束水位max(实际时间、创建时间、既有last)，防止虚拟时钟回拨绕过；这是本地调时保护策略。之后的正式结局/放弃结算尚未实现。

## REA与数据依据

沿用冻结2.7.71 ELF/metadata和e915675d现代19表。REA默认路径：

- M134707 CheckIfUnlocked，0x398424c，368字节，ev_cf19d17cdf814b5a1f1faeb8186d4b8d6dcd3c646c8ce5795dad65918ec604c1：NORMAL视图类型1直接可选；这里的1是RoguelikeTopicModeViewType，不能写成TopicMode.NORMAL=1。月度/挑战转查对应外层资格。
- M134701 _UpdateDifficultyList，0x398c930，936字节，ev_fff34a61261820ee81239dae7e5d767b48422b4a792ef60394e0ccef7f586f71：逐难度读取模式/等级解锁状态，缺失状态取0。因此不能把目录存在等同于难度已开放。
- M161094 InitRecruitSetContext.OnSelect，0x40a3c14，612字节，ev_d5573b753acef942f065f0aaba4f845dd470ce6b8d6bf6032d670236379ef895：索引选中option中的字符串，写入请求select再进入网络管线；请求不是任意数字索引。

初始分队Load的3248字节、OnSelect的844字节及TryGetModeUnlockInfo的444字节磁盘代码受保护，仅解码0/8/0字节；守卫拒绝启动提供器，不称已经逆向。Ghidra全局/热修复局限继续保留。pending内容、属性、券/藏品结构、模块列表已从声明再次定位。

Game.eGrade/outer沿用社区wire别名候选，托管字段名为modeGrade/outerBuff；game.uid目前为本地Run UUID。它们以及hp.max=0、基础可用性和初始分队的实际消费仍须原生验证。表中结局ID实际为ro_ending_*，不能照搬旧参考的ro1_ending_*；初始化暂留toEnding:null，尚未生成地图或指定结局。

## 实际验证

最终49项相关检查通过，8.76秒，Ruff零，一项既有FastAPI/httpx警告。包含18开局专项、18主题状态、备份恢复及0015/0016迁移相关范围；此前39项和故障修正专项与其重叠，不相加。两套Runtime并发创建只成功一场；49项不是历史1194完整回归或全游戏无bug证明。

专项包括3种配方、精确初值、差量一致性、重复创建/分队选择不重复写入、错误步骤/非法选项回滚、前置/不支持模式拒绝、时钟回拨冷却、活动Run的重启/备份恢复、损坏阶段/事件/布尔数量的启动前拒绝。0018→0019保留所有61张既有表的行，只新增4表/索引及版本；注入最后一表创建失败时新增表/索引/版本全部回滚。

在全新D目录 `.cache/rogue-topic-20261022/initial-runtime-v1/data` 以冻结真实19表创建两个本地账号。main_03-08一星资格是明确QA夹具，没有原生通关/发奖。创建（含重复）、分队（含重复）、稳扎稳打组合、放弃（含重复）共7次POST均200；得到1份分队藏品和3张普通待激活券（重装/术师/狙击），无干员招募/战斗。活动Run备份恢复和Runtime重开后完整sync相等；账号2没有探索。资格夹具之后，永久仓库、普通干员、钱包/理智、关卡和任务均未因这些请求改变。放弃后保留ABANDONED记录，SQLite integrity=ok/FK错误0。实际数据探针之后只补紧了GradeUnlock.state的0..2边界（探针只产生0/1），该修订由最终49项覆盖，未为记录重跑无关探针。产品DB/settings、旧EXE、上一主题QA的DB/settings五份输入摘要保持。

失败记录保留：研究命令多出一行Python造成PowerShell解析失败（执行前失败）；受保护代码守卫拒绝；首轮夹具写错StageProgress属性名；布尔损坏夹具因Python True==1被ORM脏检查抑制更新，改显式SQL写入后验证拒绝。未放松生产校验来通过夹具。

## 尚未完成与下一步

没有启动模拟器、原生视觉验收或新发行构建。实际干员招募/希望消耗/临时干员、结束初始化、地图节点、战斗与奖励、正式结局/资格和完整主题都未完成。下一步接第三步招募及保存恢复，并用一次原生开局流程确认别名、可用性和受保护分队代码的消费，不重复旧关；再继续完整首主题和其他全部原始目标。

统一证据：`.cache/rogue-topic-20261022/` 下contracts-create、rea-mode/rea-init-events/rea-unlocks、initial-validation、initial-runtime-verification。原始官方/第三方文件、存档、代码页和缓存不入Git。新检查点索引 `.cache/github-checkpoints/rogue-initial-20261022/`；远程完成以实际回读和新D恢复证明为准。
