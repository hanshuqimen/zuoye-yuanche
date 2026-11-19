# 资源分层收藏品与银行资格

进行中，完整交付目标未完成。基线c24d730/业务cf6f2772/179 Python、0036/77表，开始时工作区干净。上一轮为实质进展：三立即源石锭效果、新26/相关208检查、真实兼容及私有回读恢复；本轮不重做已过存取/关卡/剿灭。

## 问题与来源

- e915首主题rogue_1/NORMAL0金酒之杯q28是layer_char_attribute_add：每5源石锭攻速+7。旧报价/库存全用layer0，不能直接复用普通char_attribute_add代表并声称该效果完整。
- 已有M84561 Init默认消费者按效果组传入stackLayer、M84565构造收藏品；证据与局限复用[属性报告](roguelike-battle-attributes-2026-10-29.md)，不重做已完成逆向。
- 本轮新增定位M84566 _TryRecalculateStackLayerInBattle、M84616 BasicRelic.Init、M84866 CAttributeAddByLayer.DoPreProcess，全部静态完整解码（412字节等）。只准备16384字节不可变小包/41完整方法种子，SHA256 aac6bb28f1aa591e759ae98ca7a34160c5dd8327ca91d335e3eaf1d643bb1ed8。下一通过REA核实资源值/每层除数/传参，再决定服务端投影与持久化边界，不猜层数恒0或自由叠层。
- 实际导入19表e915镜像a550f5e/v077/client_verified=false，客户端冻结CN2.7.71/V070。旧适配不证明所有表/其他主题已原生验证。

## 当前范围和失败

本阶段尚无业务修改/原生输入/新战斗/授物。首次检索误将缓存内官方单行大表纳入rg并造成输出截断，改为具体代码文件/报告和只读元数据索引定位；后续不重读大表或输出官方整表。官方资料、反编译、原生证据、保存及缓存仅本地。

本地入口.cache/rogue-resource-layer-20261031/prepare_rea.py、rea-resource-layer-v1/static-diagnostic.json/static-methods.json。新REA会话必须实际检查/保存ACK、同句柄等待、公开close及实际退出，不凭旧PID续接。银行资格/正式供给/q28效果及完整交付仍未完成。

## 新REA结论及先前假设纠正

M84566默认路径412/412，证据ev_e3a369e82cf03f0452e7e7433bc79cb801894bb97dcf3f68eb3445ac70cbc292：TryGetString/Int读取资源和每层数量；除数max(数量,1)，匹配gold/另两资源键时取对应当前整数资源后整除。两个字符串槽静态双重间接值分别为encoded kind5/index33610、33611，定义^0x66/原ASCII唯一有界结果为stack_by_res、stack_by_res_cnt，诊断存static-key-diagnostic.json。未以全局偏移当作通用对象布局。

M84616默认设置传入stackLayer，ev_a02267ac3a19c2672988681b5941bc7e67e6fb2f568aa8daa98d548e976c1389；M84866取得stackLayer后尾调已核M84617 ApplyAdditionsToAttribute，ev_786e9579a228ff3951d2c4f8d7f042f9c0302a4be00873e133a02537bb958dc2。Hotfix坏指令/虚调用/片段外尾调用警告保留，复用旧M84617完整默认路径证据，不重复求解。已有M84565明确在创建内部实例之前调用M84566，故原文“不能用layer0”只能作为待核假设，现撤回把layer0本身当缺陷的推断：本批保持基础库存layer0，由原生根据同步金钱计算，不能把推导计数写回库存。

注册分派M84562静态3192/3192但REA默认段halt_baddata，多PIC/不可达移除警告；ev_83828b7e76100a3767deea2d3b4e8e76b5c10d311514e3f32c341645a4644c09不能证明完整key→类分派。保留rea-resource-dispatch-v2、mcp-resource-dispatch-v2。随后新D/已核index1仅启动到版权画面，读文件映射RVA0x2bb8000两页8192字节，SHA10d119582fb106f3992422c00c3f1fd90d3706a2a7b9f86ba754a5eeb8f70eb1；与原静态同范围相同，重新准备小包仍SHA658dffa6，未为相同字节再次启动REA。该负结果不算新增分派覆盖；需一次新效果原生代表，不能以类名/绿测证明分派/攻速显示。

v1公开close ACK5/实际句柄4370 exit0/server0、artifact保留。v2公开close ACK3/server completion0，后84178句柄缺失；Windows29576/34768实际缺席，不补造未回收的PTY末输出/包装退出码。v1/2首次分析分别50.141/48.125秒，45秒观察返回pending后均等同原请求实际ACK，不重排/重启。当前无REA待续输入。首次Windows进程守卫把当前PowerShell自身文本算入，启动前阻止；改为仅python/wsl/node/java真实进程，未杀进程。

只读加载worker34537实际exit0，0服务器/登录/点击/战斗；已实际看startup版权图，180源文件、213保护输入、index0保持，自有index1/游戏/ADB退出。首次v3副本settings.save先建certs而copytree遇已存在，运行前失败，保留；新v4只在新D目录允许合并这些新建目录。loaded-dispatch-v3/v4失败与收尾保留，不覆盖旧保存。

## 源码/API检查与下一步

FirstThemeResourceRelics独立目录绑定q26投币玩具/q27骑士戒律·新编/q28金酒之杯的完整物品/效果/条件/档案/货币摘要，语义复核每5金攻速3/5/7。实际此完整单一效果族恰三项，不扩到其他资源/触发链/未知效果。新独立RESOURCE_POLICY报价绑定效果规则/基础层数，旧报价格式/摘要保持；共享付款/发放/发现/回放/终局许可接线，库存单份基础layer0，Gold变化不写伪派生层；诊断layers()不修改永久干员或替代原生计算。

新增23检查与相关81、终局1共105不同通过，8文件Ruff、180业务AST/diff通过。覆盖完整语义、除法边界、非法/变化定义拒绝、三项购买/增量、金币5→15→14→15输入保持、重试、回滚、并发、重启/真备份、伪层数/伪发现拒绝。相关检查63464句柄后缺失，但唯一新JUnit完整81/0失败/0错误；不补造未回收退出码，也不为记录重跑。不是新效果战斗画面通过。

实际22完整sync/77表/24旧报价保持、214输入保持，真实备份/重启/新D恢复同，三实际表定义匹配；实际保存未发新藏品或金币。业务7f8c9004b591544bfcd73da59672175994ef7a315adab25b1258d4a759f5503a/180、0036/77表。源码/API效果适配已接，完整注册/选择器/原生攻速消费仍待一次新代表；q26/27消费资格、q28银行资格及正式供给均未开放，不等于自然池或全模式。

下一准备一个未游玩新节点上的q28攻速代表，可同时用新立即金币代表提供资源，复用既有招募/存取方法，不重复旧关/旧银行代表；然后从已核结算银行奖赏接收藏资格。完整Golden/断网长时/性能/Harmony/成熟EXE与所有用户目标仍未完成。

## QA23新代表、发现的结果页缺陷与修复

从真实23账号准备前的22用户副本建立Sandbox23，匹配表核ro1_n_1_3/礼炮小队/zone_1/NORMAL0；该关不在既有4种战斗ID中。只配置q28价格1与r13价格0作为显式QA，不将r13开放为正式商店商品。准备10HTTP200、旧22完整sync不变、188输入保护；两次辅助生成器字符串匹配失败在运行前拒绝，失败副本保留。源码047f748/业务7f8c9004固定。

原生worker4825/PID4060实际exit0，所属ADB/TLS/index1退出，188输入和61其他账号表保持。94HTTP均200；本局0普通战斗、仅一个新ro1_n_1_3自然失败，未重开。q28详情每5金攻速+7、一次购买seq27/n30，金币6→5/收藏1；r13详情立即+25、一次seq31/n35，金币5→30/收藏2，售罄与真实保存同。两件基础layer0，尚未证明原生攻速数值。预备近战基础attackSpeed100、间隔1.05，预期142/约0.739秒，仅为待验期望。

用户本次明确确认接受QA23三协议；重看seq9已进入主页加载、seq10公告，队列无同意勾选/下一步输入，n14 update_agreement200来源未归因，不能称模型执行了接受。没有沿用QA22确认。seq48暂停中拖放只取消选中、未部署；恢复后seq52定位、seq54朝向确认，预备近战确实部署，原生charStats有SPAWN1；未新招募。60秒录像实际59.542秒，只到部署方向确认，未覆盖有效攻击周期，因此攻速/注册分派仍待验，不重打本关补录像。录像工具仅用已确认的自有ADB PID28704/端口61619/<test-device>，未启动全局ADB或控制index0，Android录制PID5014自然结束并拉取新D，客体原件保留。PyAV19.0.2从官方PyPI安装到本地.cache/.../video-tools，未改服务器依赖/锁，第三方不入Git。

普通自然失败完成n94 battleFinish200、实际hp0/gold30、2干员/2收藏品；界面却显示2干员/0收藏品。已在新D实际存档重现：当前inventory保有q28/r13，而GAME_SETTLE.result.record.relicList=[]。根因rogue_settlement.pending只在TERMINAL_POLICY保留传入收藏品，将普通战败强制清空；与支付/获得无关，不能以200或异常计数0掩盖。已改为所有DEFEAT/SUCCESS结果均使用调用方已回放验证且排除初始分队的库存列表，不发奖/改分/改层数；旧空库存仍空。存档、评分与旧协议收据不重写。

新6结果视图回归和相关30旧检查共36通过，2文件Ruff；加前阶段105，共141不同检查/新29。新D实际23完整sync唯独QA23待结算relicList由空变为[q28,r13]，旧22完整用户保持；77表及旧收据/评分/资源/库存逐表完全同，192输入字节保持，真备份/重启/新D恢复同。业务9970664e1ec50f4083e965bbdc3507855abc29ae35de414735ed59cb898aa7c8/180、0036/77表；修正后原生结果页仍待用当前已结束存档重开核对，不重打/重新购买。当前所有原生/REA会话已结束，无待续游戏输入。

新增证据.cache/rogue-resource-native-20261031-v1/{prepared.json,native-results.json,rlv2-0094.json,finish-facts-0094.json,deployment-stats-0094.json,errors-0061.json,after-defeat-confirm-02.png,r13-bought-01.png,resource-attack-video-v1.mp4,video-analysis-v1/overview.json}及.cache/rogue-resource-layer-20261031/{ending-view-before-v1,ending-view-after-v1,ending-view-fix-v1.xml}；官方/保存/图片/录像/日志/第三方仅本地。下一只重开当前结果页验修复，然后接银行资格；攻速未验、正式供给/全交付缺口保持。


2026-10-31普通战败收藏品结果修复已原生验收：同一个已结束QA23运行新D副本重开，corrected-result-01实际2干员/2收藏品(q28/r13)，只一次gameSettle(n20)200，得分16/蜡烛+16、笔记16/200/灵感+1，返回开始探索。重开0新战斗/购买/招募/存取，29HTTP全200/异常及Lua计数0；82825/PID13948实际exit0，自有服务/ADB/index1退出，195原生输入保护及61其他账号表保持。最终新D23用户77表真实备份/重启/新D恢复同、旧22完整用户/199输入字节保持，SETTLED/gold30/hp0、唯一得分账本count2、全5战斗中QA23仅1个ro1_n_1_3。141不同检查/新29、10相关Python Ruff/180业务AST；业务9970664e、0036/77表。攻速录像未覆盖攻击周期/注册分派仍未完整恢复，银行收藏资格/自然供给/全目标未完成；下一先私有检查点，再银行资格，不复购或重打本关。


2026-10-31资源分层/原生结果页私有检查点完成：源7a0950b06915c2ed955b826c2411566a2ab8a826/业务9970664e，private e33b04da10c53c26dfd3276f04ee24778c9cf6c7、父afc30d4；2300069字节，SHA256 8d85b6133556735565d90e0249c4c69a670f817a23003be2b2284e85b0df3f60，Git blob 2cbc2b32c09b788c469eb244b3d4517fce9f32e6。实际浏览器下载双hash、新D533文件213完整历史/Prompt/fsck/干净状态恢复通过；旧195非README项、112597字符完整旧索引保持，新树198项。535历史路径/2508文本blob扫描无禁止路径/凭据标记。普通Git只读probe128原因未分类，不称源码分支直推；本次新C下载校验后移D，旧下载/备份不动。权威.cache/github-checkpoints/heartbeat-latest.json及rogue-resource-layers-20261031/upload-verification.json。原生结果修复已验、141不同检查/新29，攻速和完整注册仍未验；正式银行收藏资格/供给及完整目标未完成。完成文字晚于包，不为补文字重复打包。
