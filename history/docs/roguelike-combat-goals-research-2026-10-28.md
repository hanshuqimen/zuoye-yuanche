# 首主题累计战斗条件：计数来源研究

最新进展见末节“一次新部署样本与计数事务归档”。下列零游玩/未改业务说明保留最初研究阶段的实际范围，不覆盖末节的新代表与源码验证。

继续执行停止已取消剿灭、不重复游玩已过关卡、代表通过后批量接同类接口和匹配数据的安排。本阶段没有新增游戏输入、招募或战斗，没有修改业务源码、存档规则或发行物。业务保持39bb4405/schema0033/74表；当前新增的是下面的代码依据与未完成边界，不能记成三项条件已经实现。

## 匹配版本与三项实际条件

固定CN Android2.7.71，实际导入19表e915675d8d8a1cc97df8fa46eed27ef1bdaa9d1b0fdb07461dcabda36271ae29，傀影主题、NORMAL0及QA开放时间1792644559。APK473566842bc219e8f15945e6c3a377e97ca0d97ea064fc545dafdd8d570ae548、ELF3ece1e7b34165233fe8c3c919cf55dfcb4406b6bbc2725def2b1242b4c0a6259、metadata bf14421bbafe9c71d944ba4f97b31ecd666232640eac0829db3d84ac716ac8b8和只读方法索引30c555d4479d4a0f708b9fc61aa4ecfeb945a169e4a82586e31d243afdaa4804保持。

| 收藏品 | 实际条件 | archive身份 |
| --- | --- | --- |
| rogue_1_relic_sp02 近卫军帽 | 累计在战斗中部署干员不小于200次的情况下完成游戏结局 | special=true，group7/sort2/PCS02，无enroll |
| rogue_1_relic_sp04 古堡的子嗣 | 累计在战斗中部署干员不小于100次的情况下完成游戏结局 | special=true，group7/sort4/PCS04，无enroll |
| rogue_1_relic_sp06 “夜骇” | 累计失去不小于30目标生命的情况下完成游戏结局 | special=true，group7/sort6/PCS06，无enroll |

这三项不能套用前14普通条件的special=false校验。文案能确定阈值与完成结局前提，但还不能单独证明计数的上传格式、忽略部署口径、失血的累计范围及临时生命/恢复的处理。

## 已确认的客户端行为

- M66394 LogManualSpawn（328字节）先调用M66424追加操作日志，再检查参数ignoreCharStats；为true时直接返回，不增加charStats。否则以角色charId和计数类型0调用计数池。对应REA证据ev_11b3ae7f5a7db2ce6b75deb56f25bc9fddd45eb882a4a13bb83d9dcc61cb1c5f。因此日志中的部署行数不能直接作为有效部署数。
- 元数据中charStats是ListCounterPool<CharStatKey>，其泛型基类为List<KeyValuePair<TItem,int>>；CharStatKey含charId/counterType，CounterType枚举名包括SPAWN/DEAD/WITHDRAW。原始枚举默认值的保护解码未独立验证；不从原始偏移或默认字节单独认定完整线上枚举/JSON格式。
- 既有M66437 TakeSnapShot证据ev_abccca43d79e24dc0e522febd931a21e7b968afb4addb13d9ec045d998439e48复制计数池并生成charList。此次读取完整加载代码后，M66440 _GenerateCharList（3164字节，ev_2edb5cd8242e134c232a064efb2a11f96c3533022444a07d8205fd17a955282b）和M66441 _GetCharCommonLogList（592字节，ev_049168e1b2f851811c01f1e2b0599b51d8b882c9eaee2fca94aa713a5ec07b44）可见：后者处理高级伤害/角色信息等列表，前者有不同gameMode的角色筛选分支。没有据此把charList某个猜测槽位当部署数。
- M64060 ModifyLifePoint（716字节，ev_36af990ea97a6eb69eea7e6e947c4a68862fc5bd70145044e53f6141e11cb5ba）建立生命修改器、应用全局修改并发送事件；该包装函数自身未证明累计失血公式。M84580 _OnModifyLifePoint的静态和加载版本REA均出现坏指令/流程截断（ev_b51c6109a6687bbbea2536bde995fb4aa96161d4611a3d057e7c7b1de4b2fc0e、ev_862145361a76cc0ed71a3a520706983ebfb740e9515fc447c6770a899d31a80c）；即使线性反汇编能覆盖字节，也不能将这段伪代码当完整语义。
- 读取既有ro1_n_1_4原生v16归档，没有重打：journal为0行，remainingLifePoint0/killedEnemies1/missedEnemies8。这是空操作日志样本，不是正向部署统计样本，也不能由此证明所有战斗部署数为0。源归档SHA088491e6dfdaa47173f6af5222666fc06bb761a309461c7b203ef0d78d51a16b，journal SHA7c1b4f4aafe98f42bd93c9dee44f27014217ead328886df6fce401bb8d4527c1。

以上均为被冻结客户端的客户端实现依据；Hotfix、未解析调用和服务端累计规则仍有限制，不声称完整逆向了官方服务器。现有actionKill快照记录敌方死亡，不是部署计数；现有结算facts未保存完整BattleStats，不能事后补造旧局计数。

## 零游玩观察与实际收尾

独立D盘QA副本的worker只允许status/read_code/stop，实际队列只有status和read_code，停止通过独立stop.flag；没有tap/drag/back/战斗接口。仅读取index1/<test-transport>/<test-device>四个文件映射代码页0x25fe000/0x25ff000/0x2600000/0x2bbc000，不读取堆或认证。原index0保留，APK/资源/数据、TLS、离线与8秒Android命令校验保持。

- 原生句柄49765实际exit0，PID26556实查缺席、18443不监听；5配置HTTP全部200，0rlv2请求、0游戏输入/招募/战斗。服务、自有ADB和index1正常退出。
- QA只有local_sessions变化，59个其他账号表投影保持。新做一次当前QA的全17用户Runtime只读快照，与已验收v8源副本相同，读取前后74表不变；169个保护输入保持。没有为补记录重跑旧奖励/战斗/备份检查。
- 静态REA句柄75116和加载REA句柄96989均实际exit0/server0；22304/2676、36840/26664实查缺席。两个artifact分别297fc1c2a1f7340afb7692fcdedeccef599357b98881a765aabeff74eb6ccba6（16384字节/27种子）、2dc8456cf2168363cb52b16406f3dd04c18ca2ff77a08162f54014c62af09dfa（20480字节/23种子）保持，均5个命令/ACK完整，正常close_binary后退出。

本地权威为`.cache/rogue-combat-goals-20261028/observation-verification.json`（SHA256 3394ba19f18e5167aa8ef3602b93b6d90f696b29ea450ea0a89925c8f5a2f643），相邻verify_observation.py可复核检查逻辑；不可覆盖已存在输出重跑。原始代码页、REA伪代码/JSON、客户端资料、QA存档和日志仅本地，未入Git。

## 保留的失败与下一步

首次静态材料中M66440零解码、M66441仅4字节解码，准备器拒绝；未以其启动REA或放松代码完整性门槛。随后代码观察补足完整文件映射页。

两次45秒观察超时实际RPC分别56.391秒和51.188秒后成功；继续等待原句柄，未因超时重排或重启。加载请求首次尚未ACK时过早读取结果导致FileNotFound，后从同一完成结果读取；没有重复请求。只读文件路径/PowerShell SQL引号错误未运行成功或未产生业务写入，已纠正。观察核验v1误以为stop也在commands.jsonl，实查是独立stop.flag；保留verify_observation_rejected_v1.py，纠正核验预期后通过，未重启原生。

下一步先确认charStats实际线上序列化/忽略项与已归属角色的绑定，再将可验证计数按探索与战斗因果顺序持久化；对sp06独立确认生命损失计数源、临时生命和恢复边界。证据不齐时这三项继续未完成，禁止数journal行、把actionKill当部署或把生命净差伪装成累计损失。自然物品供给、隐藏路线、其他主题/模式及完整交付仍继续推进；不重打旧关、已过Boss或取消的剿灭。

最新完整私有源检查点仍为3bee7c0/f94052f（见[CHECKPOINTS](project-ledger/CHECKPOINTS.md)）。本报告和后续记录晚于该包，不冒称已远程备份，也不因没有业务源码修改重复创建相同源码包。

## 后续：统计序列化与可复用属性读取

新增自有工具[inspect_client_attributes.py](../tools/research/inspect_client_attributes.py)和38项针对检查。该工具只读被冻结ELF/metadata，按显式type-index查询类型及字段的属性构造函数，仅完整解释单个JsonConverter的typeof参数，其余参数明确未验证。没有改游戏结算、发奖或数据库结构；业务39bb/schema0033/74表及此前168项业务检查的范围保持，38项属于研究工具检查，不能相加冒称新玩法验收。

实际冻结文件的属性表不是最初候选的12字节token/type-range，而是经115501条marker、严格偏移顺序、image范围及构造函数身份核对的8字节token/data-offset布局，末尾2个对齐字节不作为属性。类型/方法定义共享布局本身不能断言整个metadata版本。格式参考仅用于结构验证：[MetadataClass](https://github.com/Perfare/Il2CppDumper/blob/master/Il2CppDumper/Il2Cpp/MetadataClass.cs)、[CustomAttributeDataReader](https://github.com/Perfare/Il2CppDumper/blob/master/Il2CppDumper/Utils/CustomAttributeDataReader.cs)、[Il2CppExecutor](https://github.com/Perfare/Il2CppDumper/blob/master/Il2CppDumper/Utils/Il2CppExecutor.cs)；具体结论仍绑定本地冻结指纹，不导入第三方工具或官方字节到Git。

实际从项目外D盘工作目录运行成功：

```powershell
. <workspace>\tools\env.ps1
& <workspace>\.venv\Scripts\python.exe <workspace>\tools\research\inspect_client_attributes.py --type-index 10185 --type-index 10181 --type-index 1400
```

冻结字段72860/CharStatKey.counterType明确有JsonConverterAttribute（构造函数275598），参数nativeType73240解析为Newtonsoft.Json.Converters.StringEnumConverter；不能按SPAWN整数0猜线上表示。BattleStats.charStats及计数池类型本身没有声明JsonIgnore/JsonConverter；ListCounterPool父类为List<KeyValuePair<TItem,int>>，没有直接声明接口。该元数据结论不替代一次真实正向统计样本。

REA M25956 FormatCommonLogTraceForInvestigation完整2356字节（ev_1a4e0fe488dce307ffa0bd1ebd7e63959ac144b18fc1c5f2038ba51dc910d91a）确认调用JsonConvert.SerializeObject，并使用Networker.serializeSetting。仅分析函数代码，没有执行它或读取其logToken值。M221222 getter（ev_e04da2f1122b2e398fabfebd7b6db4aeda13897f01247fecb3e0195a8d5330fd）委托IRequestHandler，不能从一个getter宣称整个配置已还原。

转换器两项排除依据：

- M32805 CanConvert（320字节，ev_81925206728c8c09256ce4619f06c8c99fee43d9f4d6bec23961029b0b518ae1）的类型holder实际绑定Torappu.IListDict，首个Type.IsAssignableFrom调用由两个System.Type/RuntimeType的slot32声明共同核对。ListCounterPool自身无此接口，System.List父类不引入游戏接口，因此该转换器不处理此池。M32804泛型上下文和M32807 WriteJson作为配套证据保留，未把其字典写法套到计数池。
- M32820 CanConvert（204字节，ev_1175c8f1026304a2ff001e4fe22e15c82b4546aca7e577a2c40fe7cb1699b3e9）要求数组、元素为值类型/枚举、秩1。ListCounterPool是列表，不满足数组前提。

本轮仅读新增两个文件映射页0x4300000/0x906e000；code-only句柄91941实际exit0，初始EMULATOR_NOT_READY后同一会话自动就绪，未重启。5配置HTTP200/0rlv2/0游戏输入招募战斗，只有local_sessions变，59其他账号表/全17用户Runtime/只读前后74表/169输入保持。M221230/M221279在小片段REA仍有尾调用或截断限制；实际OnInit末尾跳转静态绑定DontDestroyOnLoad，不能把截断误判为统计初始化公式。

REA序列化9843与转换器16941均实际exit0/server0，前者3命令/ACK、后者10命令/ACK。artifact分别2c76bd06e6489f877331b9bdd6b93febd4ef85f76a179a9802c7d94155fff622（12288字节/15种子）、55d08545ceac3cd69bc0fd902767da57aba11820d04b53eee2f0085de95a21be（24576字节/76种子）。30380/18052/5544/18552/29504最终CIM均缺席，18443关闭，index1/自有ADB正常收尾、index0保留。一次核验短暂看到5544，随后实际CIM无此进程，原脚本原样补完核验，未杀进程或重启；不猜其当时身份。

权威`.cache/rogue-combat-stats-wire-20261028/wire-contract-verification.json`，SHA256 `b20d0966ed0ba86c9dc6aa82717f45c9de09476d4422598c794f19093b4a1518`；相邻observation-verification.json/official-attribute-inspection.json、metadata-attributes-v2.xml及两个REA目录含详细证据。38检查及2文件Ruff通过，实际三类型/字段CLI与--help通过。原始代码/客户端属性输出/存档/日志仍仅本地。

失败保留：12字节候选布局被stride拒绝；属性data结尾2字节曾被误当终点不符后按实际对齐边界纠正；工具首次真实读取拒绝了fieldStart=-1且fieldCount=0的合法零字段类型，补窄范围兼容与回归后由37增为最终38检查；静态OnInit和ListDict.CanConvert不完整被拒绝，之后才取两页；45秒观察到期后继续等原请求，实际52.094秒/60.984秒返回，未重排。没有为兼容而移除构造函数、页marker或输入指纹检查。

当前三条件依然未实现。下一步选择一个历史未游玩且匹配实际首层规则的新关卡，只做一次正向部署代表；仅保存本地账号、已归属战斗的有界charStats字段，不保存认证/AES遥测。取得KeyValuePair实际字段大小写和SPAWN正值后，接部署统计持久化、重试去重、100/200两阈值及旧结算版本不变，再批量覆盖同族。生命损失源继续独立确认；不恢复剿灭、不重打ro1_n_1_4或已过Boss。

新代表准备：实际19表/NORMAL0/zone_1/1792644559下选择ro1_n_1_1“与虫为伴”，当前完整17账号保留战斗只有ro1_n_1_4和ro1_b_6，耐久文档未见本关游玩；选择证据在相邻new-stage-selection.json。匹配10EXP/3币属于既有明确基础适配，不是本轮新猜官方奖励。新D QA v2（`.cache/rogue-deployment-native-20261028-v2`）建立独立Sandbox18、明确前置关卡/导航guide/两备用招募和单候选地图，旧17完整用户相等、174输入保持，尚未开始原生。v1初次准备把CREATE的第三券直接关闭，领域正确返回409，35734实际exit1；失败存档/脚本保留，新D v2复用完成的两招募，只补激活/关闭第三券和finishEvent三HTTP200，没有重复初始化或游玩。后续原生只准一场新关，观测器仅保留受限charStats，实际原生与两累计奖励仍待完成。


## 当前进展：一次新部署样本与计数事务归档

上述“零游玩”“未改业务”和“尚未开始”是先前研究/准备阶段记录。其后从干净d3dde0aeff323145815dd12cb96eda3853f2f2d8/业务39bb启动已准备QA v2，完成唯一新关ro1_n_1_1的一次正向部署代表；没有重打ro1_n_1_4、旧Boss或取消的剿灭。现在业务已变为e5f968dcad4ae1a769f84828f73efe53ac7af05d7d3fda3418203429a385ad2e，schema0033/74表保持。当前新增的是计数协议解析与持久化，不是100/200次部署或30生命损失的收藏品资格实现。

实际原生场景：独立Sandbox18/两备用干员与地图是明确QA前置，并非本次原生招募/自然初始化。ro1_n_1_1“与虫为伴”NORMAL0/实际zone_1/开放时间1792644559，只有一次开战和一次手动部署，随后自然失败并正常结束探索。45HTTP全部200，rlv2仅moveAndBattleStart、battleFinish、gameSettle各一次；0原生招募、0旧关重打。原生表现核对到SIGNAL LOST、结算5分/+5蜡烛/+0灵感、LV0(5/200)、返回主题主页。失败是正常战斗结果，不能写成通关或网络错误。worker98045实际exit0，PID17728缺席/18443关闭，服务/自有ADB/index1正常退出，index0保持。

有界实际样本确认charStats为列表`[{Key:{charId,counterType},Value}]`；本次同一备用近卫上传SPAWN1和DEAD1，枚举为大写字符串。未保存官方认证、AES遥测或整个BattleStats。具体本地证据：`.cache/rogue-deployment-native-20261028-v2/deployment-stats-0044.json`，SHA256 f69c82f15c1867ed52f62cd421962f5a78b41c32e456b61ea2c0d1bca92ad5e1；总核验`verified-native-deployment.json`，SHA256 008e1f5ee19fdf113201c1638e8e31a5e51909a3e0ae814e75275d13915f37c6。该原生运行在新归档代码写入前，故原生证明线上格式与既有结算流，不声称直接验收了后来写入的新源码。

新源码实现：

- 协议按实际Key/Value/charId/counterType严格解码，拒绝布尔/浮点/数字字符串、未知枚举、重复键组合、额外字段和超出本地预算。4096行/总值100000是本地接纳预算，不声称官方全主题上限。SPAWN独立累加，不数journal行，不把DEAD/WITHDRAW当额外部署。SPAWN/DEAD有本次实际样本，WITHDRAW名来自冻结枚举，未新增撤退代表。
- 缺失或null池是未知；明确空列表才表示本场记录零计数。只保留所选类型，repr隐藏原始字段，不保存无关认证/遥测。仍须先校验本地登录、已归属战斗和内外ID，再解析；选中计数尚未作为角色归属或解锁资格的证据。
- 使用独立`rogue-char-stat-archive-v1`和counter codec，在现有延迟加载records中保存最小规范化计数、战斗/探索/数据hash/原结算facts hash/内容hash。与战斗终态、奖励写入同一事务，组装响应失败全部回滚。内容hash是归档一致性检查，不冒称防篡改签名。
- 原v1..v3战斗奖励facts/hash/响应及v1..v8探索完成政策均不改；旧两字段归档永不因重试补计数。新归档的同序列/新序列重试不重发奖；修改、删除或将已有计数替换为空返回409。启动按已保存战斗/探索/数据版本核对归档，损坏先拒绝、不修存档。无schema迁移，普通sync仍不加载整个归档。

验证：当前231项不同针对检查通过，40新计数/191既有相关；六文件Ruff通过。首轮仅解析102通过；归档v3为112通过/1失败，失败源于测试误要求成功新序列连API收据与revision都不变化。实查仅这两类预期写入，修正测试为恰增一条收据/当前账号revision+1，其余业务表完全保持，只补验这一失败用例v4通过，不为记录重跑已过112项。相关自然失败、Boss、换层和首次奖励118项通过。测试有一项既有Starlette/httpx弃用警告，未改依赖掩盖。

正式冻结数据验证：新源码完整读取已验证新D v2的18用户，与原生结束后的完整用户快照相同，读取前后74表逐行不变、174保护输入保持；实际原生池通过新codec/战斗绑定归档往返，未写回旧实际结算。此前旧17用户、全部18用户Runtime/备份/新D恢复证明保持，本阶段没有为补记录重复该原生或备份。新源权威`.cache/rogue-combat-stats-wire-20261028/counter-archive-source-verification.json`；检查汇总`counter-archive-checks.json`；失败XML、修正XML及相关XML均保留。

准备/核验失败继续保留：QA v1第三券CREATE直接关闭409已在新D v2复用完成招募纠正；首次新D复制profiles已存在而失败，失败v1目录/脚本保留，后续仅继续新D v2恢复，没有重跑原生/已过备份。Settings.save创建空cache曾使继续脚本的“根目录不存在”预期错误，改为核对实际hash子目录后完成。恢复上下文时旧统一句柄92092已不存在，实际终态XML确认102通过，没有重排它。

下一步：沿本次格式批量接累计部署的资格依据与100/200阈值；先核对角色/预置友军范围和完整探索因果顺序，旧未知计数不补造，不凭已保存字符串或失败局给成功解锁。sp06仍独立研究生命损失，不能用生命净差、missedEnemies或actionKill代替。两累计部署条件、生命损失条件、自然供给/所有路线/完整游戏/成熟EXE仍未完成。不再重开本次新关或旧关；后续以同类接口/数据覆盖检查推进。


## 本阶段完整私有检查点

2026-10-28部署计数源码0add12b359dc597a3d239e476d59b3863c22b8af/业务e5f968，私有上传57df263916d8a0e9ccf28ad22ebbb971dc0261ab，bundle1944020字节/SHA256 8009aee8e45f32acb4edf6e8c3f4e62e90641af61c1f44fc2159830d8c9bfc7f/Git blob bc4f599e8b287c71722c8fb7cb24816738ddecf9。469源码/170历史、471路径/2001blob扫描无禁止内容或凭据标记；旧177非README项和完整旧README保持。已实际浏览器下载双hash、private/索引/分支回读及新D全部源码/历史/Prompt/fsck/干净检出相等；仅新下载临时C文件移D。原生一次新部署/231检查/全18用户74表证明与属性工具38检查入包。getTab包装失败仅reset JS后同browser2/tab1恢复，无权限/凭据变化；手写完整SHA错误在打包前被拒绝，读取实际HEAD后继续。0新增原生重打，100/200和生命损失资格/完整交付仍未完成。授权完整bundle备用方式，不是普通源分支push。完成文字晚于包，不为文字重复打包。 权威索引`.cache/github-checkpoints/heartbeat-latest.json`及本阶段`upload-verification.json`。
