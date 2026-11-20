# 危机合约 V2：冻结资料与请求合同（2026-11-19）

当前仍未交付可玩的危机合约流程。本轮取得同版本静态表、首赛季历史配置样本及三个 REA 默认方法结果，尚未新增游戏路由、初始化玩家状态或修改存档。

## 版本及输入

基线为本机已导入的 GameData `f44199a7d34a82bdbb232674db3a3cdf9d7958230217fce3960ccafd351b7406`，包含18张表，来源固定于 `Kengxxiao/ArknightsGameData` 的 `a550f5e048bb94e7cdefc6eb97a4091f0c4c7add`。本轮从同一 Git 提交只取得 `data_version.txt`、`crisis_table.json` 和 `crisis_v2_table.json`，逐项核对 Git blob 和 SHA-256；版本全文与该基线一致：v077/rel77.0，Change 123576，2026/09/17，VersionControl 77.6.0。新增表保存在本地证据目录，未导入或激活新兼容配置。

旧表列出13个旧版赛季，V2表列出5个赛季。按本次实际系统时间，18个条目的原始结束时间均已过去；没有从这个结果推断永久商店、训练或历史模式全部关闭，也未推断边界秒的包含规则。历史赛季后续需要明确的本地时间和供给配置。

索引及分析输入均来自冻结国服2.7.71。已核对本地索引回执和输入一致：APK `0b79b85383e21a6343283bc6bfd7a9d24eb4134abf901115f757da6a5d50f6db`，ELF `3ece1e7b34165233fe8c3c919cf55dfcb4406b6bbc2725def2b1242b4c0a6259`，metadata `bf14421bbafe9c71d944ba4f97b31ecd666232640eac0829db3d84ac716ac8b8`。

## 已确认的结构和 REA 范围

声明索引中有290个带Crisis名称的类型；这只是检索范围，不代表全部方法已经逆向。

- `PlayerDataModel` 分别持有 `crisis` 和 `crisisV2`。V2玩家根包含 `currentSeason`、`seasons`、`shop`、`newRecordTs`、`nextRefreshTs`；不能把旧版玩家对象直接作为V2对象。
- V2共享表主要包含赛季索引、评级、常量和战斗评论符文。`CrisisV2GetInfoResponse` 的 `info` 另需 `seasonId`、`mapStageDataMap`、`mapDetailDataMap`、`achievementDataMap`、`seasonConst`。两张新静态表本身不包含整个可玩赛季的信息。
- `CrisisV2BattleStartRequest` 继承含 `squad` 和 `assistFriend` 的请求，新增 `mapId` 和字符串列表 `runeSlots`。

REA/Ghidra 12.1.4 已实际分析 `CrisisV2StartServiceConfig` 的 M27993构造函数、M27994服务码getter及M27995请求解析，共544字节。使用APK中可完整线性解码的有界方法及8,192字节自有分析容器，未知被调函数仅声明未初始化地址和名称，没有写入返回值或代码桩。容器 SHA-256 为 `bf71b60c168b87bc3cbb277ab9baf47a8c66d7042291c3bde218376e89e362ea`。

默认请求解析向请求对象的四个字段槽写入引用；对照metadata可识别编队、助战、地图和符文槽字段。构造函数保存地图及符文槽参数。服务码getter返回的常量指针尚未解析成具体路由文字。泛型基类布局、未知被调函数、实际加载后字节等价及Lua Hotfix仍有缺口，不能据这些默认方法推导官方计分、开放时间或领取规则。

REA公共 `close_binary` 成功保存快照，控制器及其WSL子进程实际退出0，Windows进程核对均已消失；输入指纹保持。本轮没有启动模拟器或游戏服务。

## 首赛季历史样本

只读研究了提示词参考项目 [OpenDoctoratePy-EX-Public的固定版本](https://github.com/jiellll1219/OpenDoctoratePy-EX-Public/tree/fcce42d48b8c4ead3aeb3f9628db91d3009f5db7)中 `server/crisis.py` 和 `data/crisisv2/cc1.json`，逐项核对Git blob。该项目为GPL参考，源码和原始配置仅在本地，不执行、不复制为MIT业务实现。

样本的 `info` 包含 `crisis_v2_season_1_1` 的5张地图：01、02、03、05、07。五个 `levelId` 都能对应到上述冻结GameData提交的关卡文件；这是引用对应证据，尚不证明当前客户端已消费整个样本。

需要保留的差异和缺口：

- 历史路由使用固定战斗ID和共享文件，不能作为本项目的账号隔离、事务或结算依据。
- 样本外层 `playerDataDelta` 是历史示例状态，不导入现有账号。后续只评估独立、版本绑定的信息源。
- `achievementDataMap` 为空，不能推广为全部赛季无成就。`showTip` 未给出，其实际消费及缺省行为仍待核实。
- 初步无类型区分的引用检查标出主地图奖励节点 `reward_1` 的空白 `runeId`；核对该节点实际 `nodeType=TREASURE`。它不能直接按普通可选符文判为坏引用，也未据此清洗数据或放宽普通符文校验。原始检查结果保留，下一需核客户端按节点类型的分支。

## 失败、证据和下一步

连接器与网页工具曾出现传输错误；公开GitHub API请求返回未认证限额403，未读取凭据或重试认证。改用无凭据的Git协议取得固定提交的树和三个指定blob，全部新增文件均位于项目内。

首次REA准备错误要求方法最后一条必须为RET，拒绝了正常返回块后还有错误处理调用的M27995。已保留v1脚本和目录；v2保留完整方法边界和未知调用语义，完成三方法分析，没有伪造被调函数不返回。首次样本打印误假定成就字典非空而停止；后续按实际空字典记录，未改样本。

证据根 `.cache/crisis-20261119/`：

| 文件 | 内容 |
| --- | --- |
| `frozen-tables.json`、`frozen-excel/` | 固定版本、原始表、Git blob及SHA-256 |
| `metadata-inventory.json`、`core-contract-declarations.json` | 类型、字段、声明及地址检索 |
| `reference-files.json`、`reference-files/` | 参考项目两个文件的来源和指纹，仅本地 |
| `first-season-reference-audit.json` | 五地图引用及原始、尚需类型判断的检查 |
| `rea-start-v2/static-methods.json` | 三方法边界、544字节指纹及分析容器 |
| `mcp-start-v1/rpc-0004.json`至`rpc-0006.json` | 实际REA反编译证据，原始内容仅本地 |
| `mcp-start-v1/completion.json`、`final-snapshot.json` | 公共关闭、实际退出0及未改输入 |
| `source-fingerprint-verification.json`、`research-summary.json` | 输入对应、当前时间、原始赛季时间及已知限制 |
| `next-consumers.json` | 下一批40个选择、解锁和分数相关消费者的精确方法ID与地址 |

下一先核客户端的符文槽选择、按节点类型的处理、互斥/解锁和分数消费者，再实现独立信息源与事务存档；任何历史配置都需保留版本和来源，不用万能成功或全解锁对象掩盖缺口。危机合约、卫戍协议及完整交付仍未完成。

## 2026-11-20：加载代码、节点规则与六维计分实现

此前的八个计分消费者已由REA实际分析，共4,396字节；后续全部八个方法体与受控读取的加载代码一致。第一次读取原始exec-out字节失败，未取得代码页；失败记录和清理结果保留。改用经过边界校验的ASCII/base64通道后，分别取得9页/36,864字节与11页/45,056字节，只读取明确文件映射的代码。两次属于不同启动过程，不能当成单一运行时快照。

读取仅使用index1/emulator-5556/0063090c，核APK、ELF、资源标识、GameData、CA、离线和8秒Android命令；宿主游戏API端口保留但不监听。没有游戏输入、认证或玩家对象读取，没有复制/打开玩家数据库；两份捕获回执记录宿主存档及设置指纹保持、index0不变及index1清理后停止。本轮只在本地继续分析已有代码页，没有再次启动模拟器。实际ldconsole回读两个实例均为停止。

REA另完成15个节点/进度辅助方法，以及本轮31个模型方法/10,236字节的默认路径分析。本轮容器53,248字节，SHA-256 `b354b3c767571c754ff1ad58443bb60d05792fa7933b3d8c32208d5f52639d97`。未知调用仍只声明未初始化范围，没有编造实现或返回值；公共status/close成功、输入未改，实际执行句柄59853终止且子进程退出0。Hotfix分支存在，但未读取活动Hotfix对象，不能声称全部运行时逻辑已逆向。

### 实际规则及输入边界

- 节点成员依据`nodeDataMap`；符文组成员按节点`slotPackId`，互斥组成员按`mutualExclusionGroup`建立。工厂的默认分支及APK只读跳表对应START/NORMAL/KEYPOINT/TREASURE；跳表仅核冻结文件，不冒称读取了活动Hotfix或加载后跳表。
- 普通节点的每日锁定资格来自`dailyRuneUnlcokDataMap`的成员关系，不能用时间已过直接发放解锁。永久地图的`exRunes`状态0为未知/不连通，1为已知/不连通，2及以上连通；普通非锁定节点连通。挑战节点状态大于0可增加起点。日历、状态授予及完成奖励不在本组件内。
- 可用集合从起点沿连通节点展开；GetNodeStatus的可达判断只看是否有相邻已选择节点。普通战斗槽只接收NORMAL节点，KEYPOINT可作为自动连接节点；START和TREASURE不计作普通符文。
- 六维基础分只累计已选普通节点的有效维度。符文组进度仅累计已知、可用的普通成员；目标分的互斥成员只取配置`defaultSlotId`，不是最高分。当前分达到或超过目标分时加组的附加分，包括0/0情况；无有效维度的符文不进入基础维度分，但仍可进入组进度。显示`dimensionItemList.maxScore`不用于截断得分。
- 原始配置中的TREASURE空白`runeId`不按普通符文清洗或拒绝。源码不复制GPL参考实现，也不导入样本外层`playerDataDelta`。

新增`terralocal/server/gamedata/crisis_v2.py`，规则和投影结果不可变，绑定客户端ELF、数据版本、地图及完整配置指纹。对称邻接、完整引用、整数/溢出拒绝、NORMAL请求连接与互斥检查，以及排序后的去重槽列表是本地接纳措施；不声称已经取得官方服务器的请求验证策略。未提供玩家地图时拒绝运算，不合成全解锁状态。该模块不注册路由、不写存档、不发放货币或奖励。

### 实际配置反例、修正与验证

首次35个合成检查通过后，五张实际配置核对只有永久地图通过，四张TEMPORARY地图因空`defaultSlotId`被过严校验拒绝。该限制没有足够依据，已撤回；原生getter保留空默认值，进度消费者的相等判断不会替空值挑选最高分节点。非空默认值仍须匹配本组成员。原失败`five-maps-compile-v1.json`保留，不能把首次合成通过写成实际全配置通过。

修正后38项定向检查通过，Ruff通过。冻结样本的五地图配置全部编译，按各自`stageType`执行永久图两种额外符文状态及四张临时图基础状态，共六组隔离投影，原始文件指纹和合成玩家输入保持。原始配置Git blob/SHA-256、静态表和版本回执再次对应。原始赛季已结束，未据此启用历史日历或真实客户端玩法。本次没有运行全量测试、打关、原生展示或战斗结算验收。

| 本地证据 | 范围 |
| --- | --- |
| `loaded-20261120-v1/capture.json` | 原始字节通道失败与清理 |
| `loaded-20261120-v2/capture.json`、`loaded-models-20261120-v3/capture.json` | 两次独立受控捕获及边界/清理回执 |
| `loaded-score-equivalence.json` | 八个先前计分方法体与加载字节一致 |
| `mcp-score-v1/`、`mcp-loaded-v1/` | 八个计分及十五个辅助方法的REA结果和退出回执 |
| `model-method-evidence.json`、`mcp-models-v1/` | 本轮31方法/10,236字节、来源、REA及退出0 |
| `node-factory-jump-table.json` | 冻结文件只读跳表，非活动对象证据 |
| `rules-v1.xml`、`rules-v2.xml` | 首次35项及修正后38项合成检查 |
| `five-maps-compile-v1.json`、`five-maps-compile-v2.json` | 过严默认值校验失败，以及修正后五图六组合成投影 |

下一核对独立赛季信息源、真实请求服务码、玩家状态初始化与解锁授予，再把本组件接入事务性BattleSession及结算。客户端实际消费、日历/商店、成就及奖励领取、旧版危机合约和其余赛季仍未完成。

## 2026-11-20：V2路由漏项与开战服务码对应

进一步定位到研究索引的路由白名单只接纳`crisis/`，未列`crisisV2/`。这说明旧SQLite索引缺少V2路由行不能证明客户端没有这些服务。修正`tools/research/index_client.py`后，用同一冻结元数据重新只读扫描得到118个候选，原来为111个，新增七个：`crisisV2/battleFinish`、`battleStart`、`buyGood`、`confirmMissions`、`getGoodList`、`getInfo`、`getSnapshot`。现有SQLite索引没有重建或覆盖；扫描证据单独保存。Ruff通过，没有新增服务器路由。

M27994开战服务码默认getter的REA结果读取静态间接地址`0xc171fc8`，冻结文件中的指针指向`0xc60e8b0`，其中为编码字`0xa000cf93`。按固定版本的[Il2CppDumper元数据解码参考](https://github.com/Perfare/Il2CppDumper/blob/4741d46ba9cd6159c5d853eb9d6fc48b4bfa2b1a/Il2CppDumper/Il2Cpp/Metadata.cs)，对应字符串用法5及字面量索引26569，恰为`crisisV2/battleStart`；用法分类另核同提交的MetadataClass.cs。只采用与已冻结布局及该编码字一致的解释，不拿受保护头的前两个原始字声明版本。读取范围均为冻结文件映射，没有访问活动堆字符串或认证。

这补齐默认开战getter与路由文字的对应，不代表读取了活动Hotfix、取得了全部请求校验规则或真实客户端已成功开战。其他六个字符串仍是候选，需逐项对应消费者。原始候选在`v2-literal-route-candidates.json`，修正后扫描在`route-scan-after-fix.json`，精确绑定在`start-route-binding.json`；第三方解析参考的固定提交与SHA-256保存在本地`decoder-source-4741d46/source.json`，不收入Git。

## 2026-11-20：赛季信息请求和缓存有效性

随后REA实际分析9个信息/缓存相关默认方法，共2,428字节；20,480字节容器指纹为`61cdc3c23a4129c8d11548ab61d3c1b451184af14df70438498d1b526651b272`。公共status/close成功，completion记录WSL子进程退出0，实际19104/11048两PID已消失。本次没有启动模拟器。IsInSeason方法体与前次加载捕获相同，其余八个方法未新增加载后等价证明。原准备模板错误要求每个方法含RET，拒绝了合法尾调用转发M162496；v1保留，v2撤回该无依据启发式，保留边界/完整线性解码/指纹与未知调用约束，才启动REA。

M162500请求的静态服务码已进一步对应`crisisV2/getInfo`：间接地址`0xc03ec78`到文件单元`0xc60e8d0`，编码字`0xa000cf9b`对应字面量26573。该路径构造CrisisV2GetInfoRequest，回调读取CrisisV2GetInfoResponse.info并写入缓存包装的+0x10。响应声明另有ts；没有把历史样本外层玩家delta作为初始化数据。至此默认开战和信息请求均有精确文字对应，其他五个服务仍为候选。

已核的客户端一致性要求：

- 启用赛季时，缓存验证读取玩家`crisisV2.currentSeason`和`info.seasonId`。任一非空时要求两者字符串相等；二者均为空允许空赛季状态。包装缺失或类型不匹配则无效。返回HTTP成功本身不能补齐这项一致性。
- LoadCurrentSeason还要求当前ID能在客户端赛季表和玩家`crisisV2.seasons`中同时找到，否则得到空赛季描述。后续初始化、信息响应和增量必须来自同一版本/赛季配置。
- 信息请求路径有全局`constData.sysStartTime`、UILockTarget原始值24的CheckIfUnlocked、已有缓存及跨日重同步门槛。隐藏方法上下文静态解码为ConstTable<CrisisV2SharedData,CrisisV2DB>，字段布局与全局开始时间读取对应；没有从这个门槛推断单赛季结束边界。

需要保持的缺口：GetCacheData/M162498在APK中148字节无法完整解码，本批未分析。IsInSeason默认方法转给未索引的`0x4103878`，不能据此宣布已核实赛季日历。缓存包装字段的旧索引偏移值1684300916明显异常；包装写入+0x10来自本批REA方法体，不据此擅改整份字段索引。受保护字段和泛型共享调用继续分开核对。

证据在`rea-info-v2/static-methods.json`、`mcp-info-v1/`、`info-analysis-summary.json`、`info-route-binding.json`、`info-callee-context.json`；失败准备保存在`rea-info-v1/`及`prepare_info_rea_v1.py`。下一实现版本绑定的独立赛季信息源与一致的玩家根对象/赛季初始化，再接入现有事务、BattleSession和同步；活动日历、解锁发放、结算及原生仍未完成。

## 2026-11-20：赛季判断的返回桥与信息实现

进一步读取冻结文件确认`0x4103878`并非独立日历算法，而是8字节控制流桥：读取`[x8]`后跳回M162595方法内`0x40f7008`。新增只含原始三页的16,384字节容器，SHA-256为`d352bdc4e7f067592f578d9b5d187d87d0f4dab47aaf16a1cce03e55474b0cbc`，没有改写指令或把桥伪装成已知业务函数。REA仍将该分支输出为岛调用，没有内联返回边，尚不能据此给出官方完整日历逻辑。公共状态读取和关闭成功，子进程退出0，输入保持；本次没有Android或认证读取。

证据在`.cache/crisis-20261119/rea-info-island-v1/static-methods.json`及`mcp-info-island-v1/completion.json`。GetCacheData受保护体及活动Hotfix继续未验。其后已实现独立信息源、0038玩家初始化和同步，并以独立冻结包验证HTTPS/冷启/恢复，具体范围见[信息阶段报告](crisis-information-2026-11-20.md)；明确的本地表时间政策仍与官方算法分开记录。
