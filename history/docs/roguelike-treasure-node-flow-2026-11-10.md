# 古堡馈赠节点流程（2026-11-10，研究中）

完整目标ACTIVE。开始基线fc8ad8b/业务cdfaddcb/196Python/0037-78，源码37ef0f1/privatea2317785已完成入站双hash及新D恢复。上一轮六资源奖励属于实质进展，不重验已过原生领奖、商店或关卡。

具体范围是实际e915/v077的rogue_1/NORMAL0，非全版本同版。nodeTypeData.TREASURE名称为古堡馈赠；本主题choiceScenes里有历史馈赠与命运馈赠四场景，三选项均为TRADE到明确结果页，displayData.NORMAL/itemId null，文本是随机收藏品。不同于固定石中剑的ITEM引用，不能据文本给任意全目录奖励。此前treasures空对象不能推广为本主题没有馈赠节点，也不能据一个人工图决定整类流程。

冻结metadata事件枚举无独立TREASURE事件项，但有SCENE；这只是候选调用链线索，不先行更改事件类型。当前scene_content始终choiceAdditional为空；旧REA M150515仅证明遍历choices/传additional到CreateChoice，不证明动态奖励具体格式。本轮定位M150366 CreateChoice、M153816 _OnNodeClicked、M153946 _JumpToChoiceScene，先做默认消费者与后继请求的语义验证，再设计节点绑定和奖励。

静态完整线性解码分别200/200、1364/1364、172/172，隔离只读ELF20480字节、SHA256 3bcd1e341833459af2946ec3410cf83ba584a23f22b46fe26b6b470f6ddbba88，95个完整方法种子，覆盖四页。线性解码不等于REA语义、运行Hotfix或官方后台规则已证。启动前实际Windows相关python/wsl/node/java REA进程筛选为空；新本地stdio会话exec25148已启动，尚待ready/公开open，不能凭超时重启。

证据入口.cache/rogue-treasure-flow-20261110/{scope-v1.json,decode-audit-v1.json,rea-static-v1/static-methods.json,mcp-treasure-v1}。无新业务修改、游戏API、Android或原生战斗/EXE；官方代码页/表仅D本地不进Git。下一沿真实ACK/同句柄读取REA，必要时仅补具体被调用方法，公开close并核实际退出后更新结论。

## 已返回的结果与缩小范围

v1公开open/3pseudo/close，exec25148 actualexit0/server0，18968/28412随后实际Windows缺席，artifact不变。M150366 CreateChoice ev_946af967…4f18默认及Hotfix路径均有halt_baddata截断，不能据200字节线性完整说动态奖励已证。M153816 _OnNodeClicked ev_40af3a14…a5c8主要核交互、装载焦点/关卡、发焦点消息，未给出奖励选择请求；不可把它当服务端move合同。M153946 _JumpToChoiceScene ev_ffef7a08…577c默认只创建协程状态机，真正逻辑为M154090 MoveNext，Hotfix仍截断；不从入口名称推断最终行为。

v2试提M150367/M150477/M150479/M150492/M154090静态代码，其中后四仅4/592、0/464、0/28、0/984解码，守卫阻止启动，诊断保留。v3复用已核index1/<test-device>旧只读receipt的0x3dff000/0x3e00000两页，逐页SHA与旧证据相等，不读取新内存；连同静态CreateBasicChoice生成新隔离20480字节/97完整种子，SHA26cf54bb…cd44。只覆盖构造的派生文件，不改官方ELF。首版sidecar误沿用“static only”标签，已另存原件并改正混合来源说明，artifact/seed不变。

v3第一个_CreateBasicChoice请求返回provider_timeout，不当作成功或任务终止；同会话binary_session仍open，analysis_activity/process_lineage为not_observed、provider health空，不能声称已知底层分析仍在运行。随后公开close、exec76431 actualexit0/server0，25352/28364实际缺席，不重复该请求。v4已缩小至SendSelectChoiceRequest单一旧加载页，8192字节/22种子、SHAea5812f4…17a7，完整592/592；exec92945当前已ready/open，27084/33752，原请求排队待同句柄实际ACK。若再次provider失败，再做doctor及针对性诊断，不加大猜测范围。

外部交叉材料：[PRTS主题页](https://prts.wiki/w/傀影与猩红孤钻)“事件节点”段将古堡馈赠描述为已解锁非限定收藏品，命运分支可出现更高稀有度；这是社区记录，不是官方后台概率或本地账号资格事实。“特殊玩意儿”的文字不能直接映射为isSpRelic=true。最初查事件一览页未找到手稿/石台/历史馈赠，不把未命中当不存在；主题页匹配馈赠段。当前正式概率和逐账号资格依旧缺证，不以全目录或单一空对象推导。

当前仍0业务/新游戏API/Android/新原生/EXE。下一在完整冻结来源上实现馈赠绑定与领取/回放之前，先确定选择请求、响应及动态奖励消费；先复用现有MapDraft完整内容源以保存节点结果，避免新增不必要的随机重抽入口。

## 已证请求、撤回猜测及会话收尾

v4的M150477默认SendSelectChoiceRequest ev_b05582a6…4085创建RoguelikeSelectChoiceRequest，将choice字符串写入+16，没有客户端提交奖励物品；Hotfix仍是委托分支，未证明替换后的逻辑。元数据确认选择响应items字段为RoguelikeItemBundle列表，子项sub/id/count，但不能仅凭DTO成员推断某个界面必须消费它。

v5复用另一旧加载单页，8192字节/23种子，SHAa5ae55d3…08aa。M150492 ev_556c5694…f445默认仅转发所存无参数完成动作（间接调用警告保留），M150481 ev_ea757bc1…9b42刷新场景并检查是否为空，尾端仍截断；M150479 ev_147bfd95…3e55默认门禁后构造Action，调用尾部有halt_baddata，不能补造完整调用链。因此撤回“selectChoice缺items就是缺陷”的猜测，生产响应/历史收据未为此变更，也未靠空items默认对象冒称解决弹窗。后续馈赠奖励以确定的choice请求与同步场景/库存源为依据。

v4公开close、92945 actualexit0/server0，v5公开close、39140 actualexit0/server0；四会话对应8个Windows PID独立核实际缺席，artifact均不变。共有7次REA伪代码成功返回，不等于7个完整语义证明；v3一次timeout和v2静态守卫失败保留。缩至一页后正常，不为补记录再跑doctor或相同方法。未读新内存/Android/官方认证。

## 显式馈赠方案与事务接线

新增gamedata/rogue_treasures.py：完整四场景/三选择行指纹，history/fate显式菜单及预先解析的逐分支物品、资格声明、依据和时间。复用完整效果编译/归档排除保护；金币和容量进入纯事件Delta，库存维持单份基础layer0，其他效果由现有库存/原生消费。菜单、顺序、两个分支结果均是受信方案，不能从文字、isSpRelic=false或一次QA推出真实已解锁/非限定/稀有度/概率。本地special排除本身不是完整官方资格规则。

新增内容配置v2才允许treasure池/TREASURE节点；v1结构、摘要和节点选择身份不变。完整馈赠内容仍冻结于既有MapDraft.plan，不新增表/迁移。发布经原场景服务，按区域/坐标从冻结源重建程序和候选，校验节点类型/程序名/摘要；客户端仅选choice。全部可能分支收藏品纳入已有全局无叠层资源保留，含未选命运结果，不能与战斗/商店或其他节点重复配置。这个保留约束是本地策略，不是官方分布。

领取和因果回放同读冻结选择，立即金币/容量在事件资源变换中各算一次，库存和发现同事务；重复请求不重发，另一已失效分支拒绝，旧固定ITEM事件仍用原目录和规则。程序结果投影SCENE，Map节点仍TREASURE；后继/离开/过层沿原日志。旧存档与收据保持，不给普通角色永久加属性。

当前业务97f530a2/197Python/0037-78：一个新业务模块、五个旧业务文件。162不同最终相关检查通过（新36：纯编译26/事务10，相关126）；publication-v1首轮9通过1失败仅新测试错用了squadCapacity字段，按既有capacity修正，失败保留。后轮153包含该定点及新纯26，最终按用例归并，不累加交集。范围含history/fate菜单/两类结果、金币25一次、基础layer0、容量+3一次、并发、冻结源/行/库存/金额/缺行篡改启动写前拒绝、v1拒新语义、未选分支与战斗资格冲突及重启/真恢复。Ruff8/diff通过；保留既有Starlette与一次并发Pydantic alias警告。

只读verification-v1 actualexit0为接线前的197文件编译器阶段，原196逐字节同；实际65个已完整支持效果均可在显式QA资格下编译history，fate两结果可编译，不证明65都属于官方馈赠池。其旧nonlimited_compiled字段只表示本地special过滤/显式能力，不是自然资格结论。该阶段hash f40ce0ba由后续97f530a2接线替代，旧证据保留。

publication-actual-v2/65666 actualexit0：e915/19表、rogue_1 NORMAL0/1792645099/client_verified=false，对冻结CN2.7.71/V070不称全表同版。原v1内容源字节/摘要相等，真实30用户78表先核一致，仅新31号QA以明确五层配方和放弃初始券进入两个馈赠。10HTTP为9成功、1预期409，增量/同seq收据严格相等、历史25仅一次、命运Q28基础层0、另一选择不授物；正常过层3。原30完整用户及78表全部旧业务行/旧收据保留（仅新增ID序列例外），完整31用户78表真备份/重启/新D恢复相同，原输入/保存保持。另保留实际pending历史馈赠原生种子；这是准备，不是原生通过。无Android/新原生战斗/EXE。

证据.cache/rogue-treasure-flow-20261110/{verification-v1.json,compiler-v2.xml,publication-v1.xml,affected-v1.xml,publication-actual-v2/verification.json}。下一保存源码检查点，再只做一个新的馈赠原生代表，核场景/获得/结果/地图，不重打战斗。自然菜单/池/稀有度/资格/概率与完整主题/全部模式及成熟发行仍未完成，完整目标ACTIVE。

2026-11-10 馈赠原生新代表已准备：prepare_native_v1 actualexit0，新D从真实31用户pending历史馈赠种子复制，初投影同，仅QA31 progress100/六主页引导story标记，协议说明未改；其他30用户/探索/9旧战斗保持，0新游戏初始化API/Android输入。业务97f530a2/f158d1a为本地回滚点，先只验一次新历史馈赠，再将源码与结果一并保存私有检查点；不重复战斗或进入命运节点。目录.cache/rogue-treasure-native-20261110-v1；尚未启动原生，准备不算通过。

## 2026-11-11 原生历史馈赠与恢复

v1 已进入终端，原执行句柄消失，PID 25320 和监听端口已不存在，未取回原退出码。v2 从 v1 已有保存复制后漏迁本地客户端绑定，启动报 unbound，0 HTTP、0 数据表变化，已正常退出。为该 D 盘测试副本补回 QA31 本地绑定后，在新 v3 证据目录继续同一保存，未重置原存档或重放赠礼。

v3 从 QA31 主页进入终端和「傀影与猩红孤钻」。014 画面显示「历史馈赠」及「收起手稿」，016 显示二次确认，018 显示选择后的结果文字，020 已回到第二层「落阳庭院」地图。源石锭 6→31、收藏品 0→1、生命值保持 4。观察到结果页及地图上的物品图标，未观察到独立获得弹窗。第二层「古堡馈赠」保持待进入。本轮无抽卡、开战或协议接受。

28 个请求均为 HTTP 200，其中肉鸽只有 `/rlv2/selectChoice` 两次，依次提交 `choice_treasure1_1` 和 `choice_leave`。选择响应后的同步状态已显示 31 源石锭及一份 `rogue_1_relic_r13`（无瑕宝玉，基础层 0），离开后的状态未重复发放。原生执行会话 8070 实际退出 0，只停止了本次占用的 index1。游戏进程错误级抽样中 Exception 与 Lua nil 均为 0。

独立存档审计会话 11384 实际退出 0。原 30 个用户完整状态及 9 条既有肉鸽战斗保持，旧事务收据全部保留，仅 QA31 新增两条收据。31 个用户、78 张表、馈赠日志与游标经实际备份恢复、运行时重开及新 D 盘目录恢复核对一致。原输入及源保存摘要一致。证据在 `.cache/rogue-treasure-native-20261111-v3` 和 `.cache/rogue-treasure-flow-20261110/native-save-audit-v1/verification.json`。自然池、命运分支原生表现及完整发行验收仍待完成。

2026-11-11 古堡馈赠源码 `198de025d92f8832dc1659fcfa9fb7e6b393a94e` 已回读验证。普通 Git 只读探测退出 128，经私有仓库网页向 main 新增 bundle 和清单，远端提交 `569998636fc9e981641473df8538a2baf1612ad8`，父提交 `a23177858cd53fa84465dcfc7438632ce14f39cc`。回读确认原 238 个条目及 README 字节不变。实际下载 2,822,796 字节，SHA-256 `238c47567f898d791feb5fa93764f145f43e7e394688b9053e5bce0bddf266cf`，Git blob `b003554f7bcdd7bda415fcd202669a35db9aa769`。新 D 盘目录完整恢复 609 文件、287 提交，Git fsck、Prompt 及源码字节一致。历史扫描覆盖 611 路径、3217 文本 blob，无禁止项或凭据标记命中。权威证据 `.cache/github-checkpoints/treasure-20261111/upload-verification.json` 和 `.cache/github-checkpoints/heartbeat-latest.json`。[私有检查点](https://github.com/hanshuqimen/TerraLocal/blob/569998636fc9e981641473df8538a2baf1612ad8/TerraLocal-treasure-20261111-198de02.bundle)。
