# 通关条件藏品与分歧路线资格审计（进行中）

2026-10-28已转入下一功能，没有重打Boss、重复招募或恢复剿灭。当前服务端49d4a075/schema0033/74表；默认成功结局原生消费代表已在此前独立QA中通过，完整主题/全交付仍未完成。

固定19表e915675d8d8a1cc97df8fa46eed27ef1bdaa9d1b0fdb07461dcabda36271ae29，实际主题开放时间1792644559。从具体RELIC条目筛出37项含结局/通关说明，逐项保存archiveComp的登记、特殊标记、顺序与relicParams；这只是数据合同审计，尚未接资格规则/获得/效果。不能把说明筛选器当业务解析器或开放全部物品。

其中18项同写“完成游戏结局”：c01..c12、m10/m11/m12/m16/m17/m18；这些archive.special均false，不能凭名称把整组判作特殊藏品。c07..c12实际绑定REVIEW登记rogue_1_enroll_3(1749096000)，与c01..c06不同；n01/n02属于DLC登记rogue_1_enroll_2(1655323200)。其余包含十种指定分队和希望/希望上限/金币/干员人数等限制，不能被一个成功标记泛化。sp02/sp04/sp06实际special=true，另涉及部署/失血累计，当前不能用角色数或普通过关次数替代。

匹配EASY/0明确canUnlockItem=false，NORMAL/0=true并绑定enroll3；沿用已核对的模式/时间边界，主题开放不等于全部资格已达成。当前成功账号17是合成前置的指挥分队/NORMAL0默认结局1，能作为后续事务/投影的新D依据，不能算实际Boss胜利或为其他分队造完成事实。

下一步检查这37项的具体条件分组、登记与原生解锁列表消费者，绑定保留且完整验证的本账号成功结算；区分图鉴资格、实际获得、自然供给及效果，不从资格直接授予藏品。优先接同类无附加条件的完成族与m16/n02路线资格，再推进需要新因果指标的条件；不以测试绿或目录覆盖冒称完整玩法。

本次只读研究0原生输入/战斗，未修改数据库/源码。证据.cache/rogue-ending-unlocks-20261028/matched-conditions.json；原始数据仅本地。首轮审计序列化Topic的immutable mappingproxy被asdict拒绝，未产生业务修改；v2仅保存主题原生标量与所选原始行，失败说明保留research-serialization-v1-failure.txt。

## 2026-10-28 二十项完成条件族源码与保存核对

业务16d2ab90aa9b10768e2730421a04fe83a74364e85b19c86e132303d56689f2f9/schema0033/74表。已接完整20项纯完成条件：c01..12、m10/11/12/16/17/18及n01/02；有限ID/原说明/普通archive标记/具体登记类型与时间全部严格绑定，没有中文通用解析器。正常模式门控使用实际canUnlockItem与run.started_at，物品DLC/REVIEW门控使用实际成功完成时间，不把noticeEnd当关闭时间。四个有效结局身份都可由纯规则分类，但当前已验证的实际保存仍只有默认结局1，不能说四路线已玩通。

只有本账号完整validated的SETTLED gameSettlement可提供成功事实；pending成功/失败/放弃/EASY不提供资格，重试和重复读取不累计。新增shared validated_settlement保留旧分队记录合同并校验归属；启动在旧ending/run预检后读取相同journal。完整sync和gameSettle增量投影state1/progress[1,1]，未满足state0/[0,1]；不改旧outer原始行、不重新写旧v6响应或收据，不把资格变成库存/state2/藏品效果/商店或自然供给。无依据state1/state2/进度声称，实时与只读启动拒绝。新解锁通知仍未实现，旧v6 outer.relicUnlock仍空，明确保留缺口。

当前143不同针对检查=36新增纯完成族/20项整体合成HTTP和保存检查+39当前Boss+68图鉴/招募/过层相关，全部通过；不是与旧100/151机械相加。6变更Python文件Ruff及diff检查通过，既有Starlette弃用提示保留。新检查含20项/四结局身份、DLC/REVIEW边界和noticeEnd后、模式登记与主题时间、失败/EASY/空/重复、非法成功/时间/类型/未知结局与模式、缺条目/错误special/描述/登记拒绝、不可变与同文案未知项不解析；合成成功/失败→pending→确认→delta/重试、无物品发放、只读原保存、账号隔离、重开/备份恢复和无依据资格启动拒绝。

正式冻结19表，在已验证私有1821334/49d4完整恢复源上核对全部17用户：新源只有20个collect.relic字段变化；只有原成功账号17为1，其余16账号为0，其余完整用户字段相同。pending成功原副本仍全部为0。全部74表原始行保持，Runtime/BackupService/另一新D完整17用户与74表逐项相等，160保护输入保持；0本轮原生输入/0招募/0新战斗，未再播放已过成功页。证据.cache/rogue-ending-unlocks-20261028/{validation.json,frozen-verification.json,completion-v1.xml,related-v1.xml,old49d4-users17.json,new-completion-users17.json,pending-users17.json,reopened-users17.json,restored-users17.json}。

图鉴state/progress合同沿用已完成REA M194805/194808与M154269及既有原生代表；它们证明消费方式，不是官方服务端判定代码。新通知消费者已定位：GameSettleOuterInfo.relicUnlock实际List<string>/offset64，M133758 CheckNeedTopicEnding与M133762 LoadData静态完整512/360字节（交错方法边界已按后续更正核对），单页有界ELF8192字节/SHA4291794b2407109dfb792711d188f4f0b7898c03385d76b9c46124c9d6088b64/9完整种子；不需新Android代码观察。REA新会话5570正在初始化，尚未取伪代码、不预称通知已通。当前16d2源码未新远程；旧1821334/5067355f实际回读/新D恢复保持，完整主题/其他条件/自然供给/隐藏路线/其他模式与成熟交付继续未完成。

2026-10-28 REA本地包装请求失败已核实：v1误用procedure键，wrapper5570实际exit1/server0，未发送伪代码RPC，输入SHA不变，Win5204/19888缺席；控制观察7905实际exit1，其pending输出不代表仍在反编译。失败命令/完成记录保留mcp-outer/wrapper-failure-audit.json。只在实际旧进程终态后开新mcp-outer-v2；27227会话/Win11420与8948已ready，工具schema校验完成，正确address键已排入M133758请求（74714仅观察、尚未完成）。未读Android/heap/认证、不修改保存或后端源。字段元数据已另存outer-fields.json。

2026-10-28通知REA v2实际完成并正常收尾：27227实际exit0/server0，Win11420/8948已缺席，artifact4291794b不变；M133758 ev_55a31a24与M133762 ev_8f2a6921。第一伪代码观察74714超时输出pending，但实际RPC56.156秒完成；未重排同一请求。M133762真实全局相邻方法边界是0x3958ed4，长度360字节；之前报告576误将交错的base.LoadData216字节也算入，当前结论已纠正，旧历史文字保留此更正。两个伪代码在未知throw调用后合并下一函数，且含Hotfix/baddata/重叠警告，只采纳边界内非空默认分支：outer+64(relicUnlock)正数量使需要结算页；LoadData按子模型valid选择页面。未把合并尾段/Hotfix当完整合同。详见mcp-outer-v2/bounded-findings-audit.json。

具体藏品页M136006 OnDataLoad(308字节)、M136047 Render(1448字节)静态均0字节解码，保护已拒绝，不猜列表渲染。已准备独立D code-only副本rogue-ending-notice-code-20261028-v1，账号15完整当前快照相等、163输入保持，仅status/read_code/stop可用；计划只取0x39dd000/0x39e0000两页文件映射，0界面输入/0新战斗，不读heap/认证。尚未启动该原生worker。二十资格源码16d2/143检查与17用户74表恢复保持，新通知/自然供给仍未接。

## 2026-10-28 藏品解锁页面REA完成与下一版本边界

163保护输入的新D代码观察已实际完成：83288实际exit0/PID20496缺席，5配置HTTP全200/0rlv2，0界面输入/0招募/0新战斗，只有local_sessions变化、59其他账号表投影和完整Runtime快照保持；服务/自有ADB/index1正常停止，index0保持。两页文件映射代码各4096字节：0x39dd000 SHA0aed40347350032e4d35e8a88676f059b5d8a7e3a94ad1dab700f7118590403a，0x39e0000 SHAaa0d514e1bf2b0c6c42cbafa98891fe65e0a5df9a06ffaafd7f595dce5a14cf1。仅已核对包/PID/ELF文件映射，不读heap/官方或浏览器凭据，证据.cache/rogue-ending-notice-code-20261028-v1/verified-code-only.json。

REA有界12288字节/31完整种子，artifact af94a9a43b24e153a3c038afebc56ba9ade033c89c0a120eb9d7d44d51f5ccde；M136006完整308字节/ev_ef407289，M136047完整1448字节/ev_fb96f3f5。默认OnDataLoad从settleInfo.outerInfo.relicUnlock数量启用页面；Render按传入顺序读取每个字符串，TryGetItem(topicId,id)取得具体条目后调用RelicItem.Render，使用列表数量生成标题；另将relicBp结构交AddBP视图。Hotfix/全局重叠/未解析的通用调用限制保留，只说真实默认消费者，不说官方服务端规则。观察62286曾pending，原RPC50.125秒完成，无重排；第二RPC0.14秒。6800实际exit0/server0，Win11540/8140缺席，artifact保持；当前无本轮原生/REA进程。证据mcp-relic-notice/verified-consumers.json。

解锁通知/奖励尚未写入新协议。冻结全局constant.relicTokenRatio=10只是字段事实，不能直接推广为本主题解锁奖励；[PRTS首主题规则检索摘要](https://prts.wiki/w/傀影与猩红孤钻)给出每项额外25蜡烛的候选规则，当前页面正文已打开部分、后续find超时，不能称金额正文已逐段复核，也不能称它是官方服务端源码。原始本地常量已保存relic-bp-constants.json和archive-unlock-constants.json（后者过宽读取已收窄到原生标量，未作业务改动）。下一步核定具体主题/版本及奖励含义，再加版本化通知与奖励；本轮没有把10或25写入发奖逻辑。

下一实现采用新结算策略，保留旧v1..v6响应/哈希/收据。新策略需覆盖本配置的全部结束类型，记录顺序号及前一结算的ID/哈希，用已验证的本账号历史前缀计算新资格差集，避免后来的结局改变早期通知、同秒时间排序或重复提示。用单条前驱关联而非每行复制全部历史，避免保存大小随局数平方增长；目前是待实现设计，不预称已经接通。资格、实际获得/效果和自然供给保持不同合同。旧143当前检查/正式17用户74表160输入恢复保持，未为记录重跑；完整交付目标继续未完成。

### 2026-10-28 二十通关资格/解锁页REA检查点完成

源码e1ff537e108175bd7fb649cd61e30b248c2e8071（实现e58ca67），业务16d2ab90；私有上传/索引df7acbdcfa21c0fa448abed25b0f230d9b25e63d（父5067355f70a513142f0092af6314791766173738），树50bfd2144d4493a8398bab318e04ab34c75d7369，README blob c362cda513d727ecdd897d8d7fa36135e3c352ae。完整bundle1884371字节/SHA256 ddbd25134b177a9bd4d82c3194d23a031b0c07ee8922d62b3f2d514b2f5ac43b/Git blob819412b58819c5cf92e55280e167a9c3edffdca5；455自有文件/160历史提交、457历史路径/1897blob扫描无禁止项/凭据标记。174旧非README条目和原索引完整后缀保持，176远程根项。私有可见性、固定提交head/tree/README逐项实际回读匹配；浏览器View raw实际下载双hash/Gitblob相等，新D restored-remote-e1ff537完整源码/历史/Prompt/fsck/干净检出恢复通过，只把本次已校验C临时下载移D。旧备份/保存/资源/发行物/Git历史保持；授权完整Git bundle备用方式，不称codex/development普通push。

包内包括20有限通关资格/143当前检查/正式19表17完整用户仅20字段变化、74表原始行/160输入/Runtime备份新D恢复，以及解锁页REA/新两页代码观察5HTTP全200、0rlv2/0游戏输入/163保护输入与实际正常收尾。通知/奖励/自然供给/其余条件和完整目标未完成；原始素材/代码页/数据/保存/收据/凭据未上传。权威.cache/github-checkpoints/heartbeat-latest.json及rogue-ending-unlocks-20261028/upload-verification.json，checkpoint-proof.png已保存；本完成文字晚于源包，不为说明重复打包。
