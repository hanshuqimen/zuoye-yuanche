# 首主题Boss结局路由与默认结束链路（进行中）

当前业务7e2fe0bc89ceda7286503f6dc02fa51445f3f88cec8b47e23b7b0e2ecfec0654/schema0033/74表。已新增四个最终Boss的身份/分歧路由目录，以及NORMAL/0、指挥分队、完整普通五层显式方案的默认ro1_b_6结束分支。合成协议已通过完美胜利/损血胜利/自然失败→pending→gameSettle→重试/恢复；这不是一次真实Boss胜利，也不证明官方最终奖励等价。原生成功页面、自然地图与其余Boss结算仍在进行；分队次数投影后续进展见末节，完整目标保持未完成。

## 依据与不推广范围

固定CN2.7.71、19表e915675d8d8a1cc97df8fa46eed27ef1bdaa9d1b0fdb07461dcabda36271ae29；主题在1792644559实际开放。已对九份原始签名Boss关卡资源重验RSA/PKCS1v1.5/MD5签名和SHA256；只使用既有有界waves投影识别实际敌人，不声称完整解码、所有动态敌人必出或完整战斗校验。原始基包与当前安装APK指纹分开，沿用已验资源基线，不冒称两个APK哈希相同。

四个最终关卡是覆水难收/别无所求/诸事不顺/再启新篇，分别出现enemy_2016_csphtm、2018_csdoll、2019_cshost、2020_cswrtr；与当前四项endings、名称、图标/优先级、精确levelId和区域放置绑定。第三层五个Boss均是中间领袖，不能当通关结局。endingDetailList是回顾文案，不能当服务端映射表。

表中明确的change_stage只有两项：残破的玩偶m16将ro1_b_6换成b7，初幕n02将b8换成b9。目录逐字段验证结构，不从中文说明猜替换。第五层携带恍悟/初幕进入第六层及四种终局条件依据[PRTS玩家规则](https://prts.wiki/w/傀影与猩红孤钻#结局)，是版本化社区适配，不是官方服务端代码；检索摘要与冻结资源互相核对，正文抓取超时未当作已读正文。八种分歧物品组合在正式导入数据上核对通过；目录能分类不代表这些物品已能自然获得或四条路线已可玩。

REA沿用上一阶段M151943/151944/151666已实际完成的结束消费者：成功标记来自pending.brief.success，结算响应只接后续评分/外部页；EndingRecord.relicList为List<string>的字段类型已核对。未复制/执行公开参考服务端；TerraPS固定1731c82文件仅只读参考，它的简化pending/固定奖励不作为官方规则。官方资源、伪代码和全部原始报文仅本地。

## 已接入的具体行为

新battle policy rogue1-normal0-default-terminal-boss-v3及ending policy rogue1-normal0-default-boss-ending-v6，与旧v1/v2和旧五项失败评分policy共存，未重算旧保存。只接明确五层zone_1..5、完整四条过层journal、第五层最后节点ro1_b_6、已支持分队/效果/模式；隐藏路线、其他领袖、跳层/重排/第六层方案拒绝，原探索保留。普通胜利不能调用该终局分支。

已验证开战归属、编队及结束记录后，根据现有生命规则区分rank3完美/2损血/1失败；成功生成GAME_SETTLE(success=1, ending=ro_ending_1)，失败success=0且不发通关奖励。新终局没有伪造随机藏品池。当前把区域基础50经验/7币直接记入终局胜利的探索状态，不再发后续招募券/独立领奖页；基础值沿用原PRTS区域适配，立即入账及终局不领奖的顺序是本地v3策略，尚需原生/官服依据核对，不能预称与官方等价。失败不加经验/金币。

结束事件包含第五层/实际已获藏品引用；正常成功评分计5完成层、1领袖，失败计此前4完成层、0成功领袖。账本、蜡烛/灵感上限、外部stageCnt与SETTLED同事务提交，重复或并发确认读同一结果；新序号不二次扣发。已成功的pending不能用giveUpGame丢弃。依然没有把未实现的分队勋章、通关条件藏品、分歧物品自然获得或高级模式自动开全。

## 当前检查与失败

本轮汇总151不同最终通过项：37新Boss/路由/事务检查、79相关、35较早失败结局基线；后35早于本轮严格启动/数值类型/成功放弃守卫，未为记录重跑。79相关和完整16用户对照在当前字节源执行；新增守卫、回滚/并发在守卫加入后补验。不能说151项全部曾在最终字节源重跑。

新检查涵盖四结局身份/八种分歧组合、全部五个中间Boss、错误区域/缺失/冲突物品、改名/level/布尔标记/数值/阶段替换拒绝、不变目录；默认五层合成请求的三种结果、delta、重试、成功/失败统计、正常钱包隔离、重开/备份恢复；battleFinish与gameSettle注入回滚、并发只结算一次、成功不能放弃、不完整percent拒绝、末层/完整地图/保存终局篡改启动前拒绝。

首轮34中31通过/3失败：旧QA表有无type的无关非藏品行，目录枚举错误要求所有无关物品也具该字段；修正为只选择明确RELIC，关键分歧物品仍严格验证，3项补验通过。后续回滚/并发检查1通过/1失败：夹具笔记上限200而测试期待439全额；修正测试同时核对总分439/实际入账200，未放宽上限。格式诊断已修正。原34601观察句柄随后不存在，按已完成XML核对终态/失败内容，未重启原测试；不凭观察缺失伪造成功退出码。

正式数据用新D副本对比已私有恢复的6b2aae4/72754635完整源树：全部16用户逐字段相同，74表原始行相同、146保护输入保持；Runtime/备份/新D全部用户和表恢复通过，0新原生输入/新战斗。旧35基线与79当前相关的Starlette警告保留；九个变更Python源码/测试Ruff与diff检查通过。

证据`.cache/rogue-boss-ending-20261027/{validation.json,legacy-verification.json,matched-route-verification.json,signed-boss-level-audit.json,boss-v1.xml,boss-fixture-v2.xml,boss-atomic-v3.xml,boss-guards-v4.xml,legacy-ending-v1.xml,related-v1.xml}`。源树7e2fe0bc尚未新远程回读；旧6b2aae4检查点保持，不将后续内容冒称在旧包内。

## 正在继续

分队通关记录具体消费者M161045 _GetEndingFromBandCnt/M161046 _GetEndingFromBandGrade静态仅4/956、0/1340字节解码，已保留static-diagnostic拒绝，未把保护字节交给REA当有效代码；字段取向不能凭嵌套字典猜。下一步仅index1读取相应文件映射的一页0x409f000，0游戏输入/0新战斗，停止后再继续REA和记录接线。随后只做一次新的成功结束页面代表；不重复失败结算、招募或旧关，不恢复剿灭。完整主题、其他模式、成熟EXE/Golden/两小时/断网/性能/Harmony仍未完成。

## 2026-10-27 分队结局记录/成功页面前置

业务源49d4a075289f4ca47a334276ecc2f34e76bccbad10982bad6a96555c3326234a，schema0033/74表。已接入结算journal只读分队次数投影：只计归属本账号、已完整校验、SETTLED、NORMAL/0、默认指挥分队及结局1成功；pending/放弃/失败不计，重试/并发不重复，bandGrade不编造，保存中的无依据次数/难度标记拒绝。旧原始outer行不因同步重写。只读投影不是四条隐藏路线或所有分队的通关支持。

M161045/46静态保护拒绝之后，index1仅取文件映射0x409f000一页4096字节，0输入/0新战斗，14HTTP全200/0rlv2，只有local_sessions变化，144保护输入与Runtime快照保持；19792实际exit0、PID10336缺席、服务/自有ADB/index1正常收尾。REA使用8192字节有界ELF/4完整种子，M161045完整956字节，M161046完整1340字节；evidence ev_95c19eb6dd12da5901eccb45ec2b54d29eced21f98ea80a83542ed721edb8c8f / ev_8692064c4a6f404ac2368a90146d002e033317d6aa4ea2a9a294296d9bf15bf3。确认bandGrpId→record.bandCnt→ending→正次数加载icon0；另一路bandGrade缺值-1、>=0加载难度图标。匹配表initialBandShowGradeFlag=false/bandRef={}，首主题只实现次数，不把其他主题难度徽记规则套用。Hotfix/重叠全局/不可辨间接调用限制保留。81447实际exit0/server0、Win38448/10272缺席、输入artifact SHA70df6a6f7c3119ea360153dadf954cdc3d404b36207c01a902afde2cc94ecfc1保持；未读heap/官方或浏览器凭据。

当前字节源39 Boss/分队检查及61状态/初始化/旧失败结算检查共100不同用例通过，3变更Python文件Ruff通过；旧151是各自先前基线且有重叠，不直接加总。正式19表新D账号17合成成功前置24HTTP/delta通过，只供成功页消费，不是真打赢Boss；所有旧16完整用户/74表既有行/149输入与Runtime/备份/新D保持。随后49d4源新D band-qa-v2确认一次437分结束/次数1/新序号重试保持，旧16完整用户保持、全部17完整用户及74表Runtime/备份/另一新D恢复相等，152输入保持、0原生输入/新战斗。研究脚本v1误把LocalSession.token_hash当可读secret字段而失败；仅新副本v2创建自有账号本地会话，旧失败目录保留，不读任何外部认证。

一次新的成功页原生fixture已准备于rogue-boss-success-native-20261027-v1：独立D副本账号17、6项导航story前置及progress100，无额外奖励，153输入保持；只允许该自有账号gameSettle，阻止其余rlv2/普通/剿灭开战。尚未启动，不能标原生通过。终局直接50经验/7币/无领奖页仍本地v3策略，官服等价与通关条件收藏品仍待完成。

证据：.cache/rogue-boss-ending-20261027/{band-validation.json,band-verification.json,success-fixture-verification.json,mcp-band/completion.json,band-record-fields.json}；.cache/rogue-boss-band-code-20261027-v1/verified-code-only.json；.cache/rogue-boss-success-native-20261027-v1/prepared.json。完整主题/自然地图与供给/其余终局/其他模式/成熟EXE/Golden/两小时/断网/性能/Harmony继续未完成，取消剿灭不恢复。源49d4未新远程；旧6b2aae4/55c5de39实际私有回读/新D恢复保持。

### 2026-10-28 成功页原生恢复点

恢复时原观察句柄2972不存在，PID37804/CIM与18443监听缺席，无adb/python原生进程，index1实际停止；v1无native-results，不能补造最终退出码或宣称验收通过。只保留19个HTTP全200至本地SDK说明确认/同步推送，账号17仍MAP_READY/pending成功，0gameSettle/0新战斗；六导航前置和本地说明已在该QA副本，原始success-qa-v1保持。已新D准备rogue-boss-success-native-20261028-v2，原始QA及v1/157输入受保护，完整pending快照一致，仅放行自有17的gameSettle，未重开Boss或取消的剿灭。下一步只验新的成功结束页；原v1结束原因未确立，不能把句柄缺失解释成正常成功收尾。业务仍49d4a075，完整目标保持。

### 2026-10-28 新成功结局页面代表通过（合成前置，0新战斗）

v2源fc850db/业务49d4a075/schema0033/74表，index1/<test-transport>/<test-device>及APK/TLS/离线/8秒守卫保持。27HTTP全200，肉鸽只有一次gameSettle，无createGame/招募/开战/结束战斗、0新战斗；成功剧情→舞会终场(指挥分队/风笛)→评分5层400+5步5+领袖1次30+招募1次2=437→蜡烛+437、灵感+43/笔记LV2(37/200)→主页开始探索，screen11/13/14/15已逐张原生查看。零耗时合成夹具的“历时”为空，不能推广为真实游戏计时正确；分队选择页徽记未另开新局验，终局直接奖励/无领奖页仍本地策略，未冒称官服等价/真实打赢Boss。

59其他账号表投影与157输入保持，旧16完整用户相同，原生完整rlv2等于独立合成确认结果；账号17只有一个已验证SETTLED结算，bandCnt结局1次数1。Runtime/备份恢复及另一新D完整17用户/74表逐项相等。errors0030未见当前游戏进程异常类型/JSON路径/Lua nil；只涵盖该有界日志窗口，不证明全游戏零bug。90940实际exit0，PID33116缺席，服务/自有ADB/index1正常停止，index0保持。v1缺少终态记录仍保留，不因v2成功覆盖。

证据.cache/rogue-boss-success-native-20261028-v2/{verified-native-success.json,native-results.json,final17-users.json,reopened17-users.json,restored17-users.json,screen-11.png,screen-13.png,screen-14.png,screen-15.png}；all74保存及官服素材/代码页仅本地。当前100针对检查与较早151分别按基线留存，不为记账复跑。下一功能是成功结束条件的图鉴资格/分歧物品可获得合同，需匹配实际版本/登记/模式与REA消费者，不从中文说明直接发藏品；不重打Boss、不重复失败页、不恢复剿灭。完整集成战略主题、自然地图/供给、其余终局、其他模式及成熟EXE等全部未完成。下一步保存这一源码/原生进展的私有检查点，新远程尚未完成前仍以6b2aae4/55c5de39为最后完整回读恢复。

### 2026-10-28 默认Boss结局/新成功页检查点完成

源码1821334fd78cb01e8d75a7953f35bca303cdd134/业务49d4a075，私有上传与索引5067355f70a513142f0092af6314791766173738（父55c5de399498b0fef57ee6fafa0448d862239aae），树584eb899775e28466e647970a66bbbfbd1e535dc，README blob f22c4dfece5c77a103fb56234a9a5bfdb80a1c45。完整bundle1857957字节，SHA256 616d52740500201d8d7352d5b4f947cbd382056b4c1c49edac8db19f46cf35b8，Git blob b1317f931878c55579a5199a0ce98685eb45a4a0；452自有文件/154历史提交、454历史路径/1851blob扫描无禁止项/凭据标记。173旧非README条目与完整原索引后缀保持，175远程根项，私有可见性/固定提交索引/tree/head实际回读匹配。浏览器View raw实际下载双hash/Gitblob相等，新D restored-remote-1821334完整源码/历史/Prompt/fsck/干净检出恢复通过，只把本次已校验C临时下载移D。旧备份/客户端/资源/保存/发行物及Git历史保持；连接器完整Git bundle授权备用方式，不称codex/development普通push。

包内包含当前默认成功/失败结局版本化链路、四Boss身份分类/未开放隐藏路线边界、分队次数投影、100当前针对检查/正式19表旧16与完整17用户/74表/恢复、REA M161045/46和新成功页27HTTP/1gameSettle/0新战斗的实际证据摘要。官服终局奖励等价/真实Boss胜利/分队选择标记/真实计时/通关条件藏品/自然地图与供给、其他模式及成熟EXE/完整验收仍未完成。权威.cache/github-checkpoints/heartbeat-latest.json及rogue-boss-ending-20261028/upload-verification.json，网页截图checkpoint-proof.png已保存；本完成文字晚于源包，不为说明再次打包。下一步通关条件与分歧物品的实际资格/获得合同，不重复旧关或恢复剿灭。
