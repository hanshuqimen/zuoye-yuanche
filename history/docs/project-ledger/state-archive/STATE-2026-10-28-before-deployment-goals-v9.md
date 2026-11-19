# 当前状态与按需入口

完整交付目标仍在进行、未完成：抽卡、战斗、集成战略、卫戍协议、剿灭、危机合约及Prompt全部系统、原生视觉、稳定/完整断网/性能/Harmony与成熟EXE。详见[REQUIREMENTS](REQUIREMENTS.md)。不恢复已取消剿灭、不重打已过Boss/旧关；代表通过后按类接接口与匹配数据。

## 当前基线

- 当前业务e5f968dcad4ae1a769f84828f73efe53ac7af05d7d3fda3418203429a385ad2e，schema0033/74表；新增严格charStats解析与战斗绑定计数归档v1，事务/幂等/回滚/重启校验已接，旧v1..v3战斗和v1..v8探索收据不改。当前231不同检查（40新/191相关）及6文件Ruff通过，正式全18用户/74表逐行不变、174输入保持，旧未知不补造；100/200和30失血资格仍未接。[当前报告末节](../roguelike-combat-goals-research-2026-10-28.md)。
- 先前业务39bb4405df1909d047f44a0f76a14aaa9abf2981f60abcb535231bdd5076f4f5，schema0033/74表，新增14通关附加条件（10分队/剩余希望8/希望上限60/队伍15/源石锭50）资格和v8首次差集奖励，R28已有获得不重发；旧v1..v7 hash/响应/收据保持。10分队条件不等于全部开局可玩，资格不授实际库存或自然供给。[当前报告](../roguelike-conditional-endings-2026-10-28.md)。
- 当前168不同受影响针对检查通过（40新纯合同/6新HTTP+122既有），9文件Ruff通过。正式19表旧17用户只增加14资格、旧74表/v7结算保持；实查17剩余希望20同时满足a03/q05，新独立pending确认22项/额外550→987蜡烛、55额外→98灵感；已有R28实际归属13/15保留。完整17用户74表Runtime/备份/新D恢复、166输入保持。fixture manifest/分队别名、两次冻结预期错误均保留后纠正；未放松正式规则。
- 固定CN Android2.7.71，19表e915675d8d8a1cc97df8fa46eed27ef1bdaa9d1b0fdb07461dcabda36271ae29，实际topic开放1792644559；仅index1/<test-transport>/<test-device>，index0保持。APK/资源/数据、硬件、TLS/离线/8秒Android守卫保持；完整断网验收仍未完成。
- 默认五层ro1_b_6终局v3/结束v6及分队次数已接；先前49d4上的新成功页面代表27HTTP/1gameSettle/0新战斗，舞会终场/437分/+437蜡烛/+43灵感/回主页通过及完整17用户恢复。该成功来自明确合成前置，不是真实Boss胜利；直接50XP/7币/无领奖页仍本地v3策略，官服等价/分队选择徽记/真实计时待验。[结局报告](../roguelike-boss-ending-2026-10-27.md)。四最终Boss目录分类不等于四路线已可玩。

## 保留的先前研究与通知终态（历史）

- 最新新通知原生50319实际exit0，PID3960实查缺席/18443关闭，自有ADB/index1正常停止、index0保持。42HTTP全200、唯一gameSettle/0新招募战斗；20收藏品/+500蜡烛/+50灵感/LV4(137/200)/主页93通过。59其他账号表/旧16完整用户/163输入保持，最终17用户/74表Runtime备份新D恢复相等。短SHA和错误tap键均在输入前被拒绝，失败保留。
- 当前无本轮原生/REA进程。最新code-only观察49765实际exit0/PID26556缺席、18443关闭，5配置HTTP全200/0rlv2/0游戏输入/0招募战斗；只有local_sessions变化，59其他账号表投影/169输入与全部17用户Runtime快照保持、只读前后74表不变，服务/自有ADB/index1正常停止。旧83288/20496观察和163输入证明保留在原报告。
- 新计数研究REA75116/96989实际exit0/server0，22304/2676/36840/26664实查缺席，两个artifact不变。M66394先写日志再按ignoreCharStats决定计数；M66440/41完整加载分支不证明charList某槽位是部署数；M84580加载仍坏指令/截断，不能采其部分生命公式。三项仍未接通，未改业务源码。[当前研究报告](../roguelike-combat-goals-research-2026-10-28.md)。
- 后续code-only91941/REA9843和16941实际exit0/server0，五相关PID最终缺席/18443关闭。新增两页，5配置HTTP200/0rlv2/0游戏输入战斗、17用户Runtime/74表/169输入保持。新属性工具38针对检查及真实冻结文件CLI通过：115501个8字节range、counterType的StringEnumConverter已确认；ListDict与数组转换器不适用计数池，实际Key/Value大小写正向样本仍待取。业务39bb不变，三条件未实现；详情见当前报告末节。
- REA解锁页6800实际exit0/server0，Win11540/8140缺席，artifact af94a9a43b24e153a3c038afebc56ba9ade033c89c0a120eb9d7d44d51f5ccde/12288字节31种子保持；M136006(308)/136047(1448)确认relicUnlock ID列表逐项lookup/render/数量与relicBp显示。Hotfix/全局及未解析调用限制保留，不是官方服务端判定。
- 早先通知通用页27227实际exit0；M133762真实长度360，先前576误含交错base.LoadData216已更正；throw后伪代码合并尾段不采纳。旧包装键错误5570 exit1/server0、失败命令与现场保留；观察超时不等于RPC失败，均未因此重排请求。细节只按当前报告/证据读取。

## 正在做什么与下一步

- 已完成一次新关ro1_n_1_1正向部署代表：45HTTP全200，仅moveAndBattleStart/battleFinish/gameSettle各一，SPAWN1/DEAD1实际Key/Value字符串池；自然失败5分/+5蜡烛/+0灵感并回主页。0原生招募/0旧关重打；Sandbox18/招募/地图为明确QA前置。worker98045实际exit0/PID17728缺席/18443关闭，index1/自有ADB正常停止，index0保留。旧17/全部18用户74表Runtime备份新D恢复及174输入保持。
- 原生在旧39bb/d3dde0a上取样，之后才写新计数代码。新源码e5f968严格解析、最小版本归档、原子保存、冲突重试/旧不补写/启动损坏拒绝已完成；231针对检查和全18用户/74表只读兼容通过。112过/1失败的测试误期待成功新序列无API收据/revision，按实查纠正并仅补验失败项；失败记录保持。不是新计数源码的再次原生验收。
- 下一批量接sp02/sp04的100/200部署资格：先核对已归属/预置角色范围与同一探索顺序，再接阈值和新版通知差集；旧局未知不改成零、不追发。sp06生命损失源仍独立未确定，不用净生命差猜。三个累计条件、分队能力/全部实际开局、分歧/自然供给/隐藏路线、其余主题和完整交付均未完成。
- 不恢复取消剿灭、不重打ro1_n_1_4、旧Boss或刚验证的ro1_n_1_1；后续同类接口和匹配数据用覆盖检查推进。当前无本轮原生/REA/pytest运行任务。当前源码0add12b/业务e5f968及属性工具已纳入私有57df263完整检查点；实际二进制回读和新D469源码/170历史恢复完成。完成文字晚于源包，不为记录重复打包。

## 最近完整私有检查点

- 2026-10-28部署计数源码0add12b359dc597a3d239e476d59b3863c22b8af/业务e5f968，私有上传57df263916d8a0e9ccf28ad22ebbb971dc0261ab，bundle1944020字节/SHA256 8009aee8e45f32acb4edf6e8c3f4e62e90641af61c1f44fc2159830d8c9bfc7f/Git blob bc4f599e8b287c71722c8fb7cb24816738ddecf9。469源码/170历史、471路径/2001blob扫描无禁止内容或凭据标记；旧177非README项和完整旧README保持。已实际浏览器下载双hash、private/索引/分支回读及新D全部源码/历史/Prompt/fsck/干净检出相等；仅新下载临时C文件移D。原生一次新部署/231检查/全18用户74表证明与属性工具38检查入包。getTab包装失败仅reset JS后同browser2/tab1恢复，无权限/凭据变化；手写完整SHA错误在打包前被拒绝，读取实际HEAD后继续。0新增原生重打，100/200和生命损失资格/完整交付仍未完成。授权完整bundle备用方式，不是普通源分支push。完成文字晚于包，不为文字重复打包。

- 最新3bee7c0749867b11325094151560319a4f12424f/业务39bb4405，私有上传f94052fc1e111bae84d9e64ad4eb835c01f8adcd。bundle1922990字节/SHA256 fa7454af7e5200d7f91e220dce6206e9d933ba92ec919bb962d85473b49133b4；463源码/165历史、465路径/1955blob扫描0禁止或凭据命中，旧176非README项/原README全文保持。实际浏览器下载双hash/索引/private和新D全部源码/历史/Prompt/fsck/干净检出相同；仅新临时C下载移D。浏览器包装失效与连接器二进制解码失败保留，仅reset JS后同browser2/tab1恢复，无权限或凭据变更。完成文字晚于包、不重复打包；不是普通源分支push。
- 最新源码3696eb1930e4909ae1fa2619a2ebc98e9e24cf9c/业务822370e3，私有上传613e0cab52e8ea35b0968e320a9ecd331981881b。bundle1913853字节，SHA256 53ba18e3ce03bf54eb7e0e806dba61929cdf8284012a3c5900a91162a5378841；459文件/163历史、461历史路径/1929blob扫描，无禁止内容；实际浏览器下载双hash/索引回读与新D全部源码/历史/Prompt/fsck/干净检出恢复通过，旧175非README项和原README全文保持。仅新下载临时C文件移至D。完成文字晚于源包，不重复打包；不是普通源分支push。
- 源码e1ff537e108175bd7fb649cd61e30b248c2e8071/业务16d2，私有上传与索引df7acbdcfa21c0fa448abed25b0f230d9b25e63d。bundle1884371字节，SHA256 ddbd25134b177a9bd4d82c3194d23a031b0c07ee8922d62b3f2d514b2f5ac43b；455文件/160历史，实际下载/索引回读和新D全部源码/历史/Prompt/fsck/干净检出恢复通过，旧174非README项保持。授权bundle备用方式，不称普通源分支push。完成文字晚于源包，不重复打包。
- 权威.cache/github-checkpoints/heartbeat-latest.json与rogue-conditional-endings-20261028/upload-verification.json；[CHECKPOINTS](CHECKPOINTS.md)含完整哈希和全部旧回滚点。

## 必要证据与历史入口

- 当前.cache/rogue-ending-variants-20261028/frozen-verification.json；针对XML见.cache/rogue-ending-unlocks-20261028/variants-{base-v1,related-v1,http-v2}.xml。先前REA消费者/代码观察按当前报告链接读取。原始数据/客户端/代码页/保存/日志仅本地，不提交。
- 当前研究.cache/rogue-combat-goals-20261028/observation-verification.json（3394ba19）及mcp-combat-{core-v1,loaded-v2}；0新游玩、17用户/74表/169输入和实际进程终态通过。观察超时/过早结果读取/stop队列预期失败均保留，未因此重排请求或重启。
- 最新统计研究.cache/rogue-combat-stats-wire-20261028/wire-contract-verification.json（b20d0966）及两个REA目录；38工具检查/真实冻结CLI和新code-only终态通过，零字段sentinel/属性布局/静态保护/观察超时与瞬态PID核验失败保留。研究工具晚于旧私有包，不冒称已远程保存。
- 先前招募/图鉴/楼层/费用/商店与其他系统只在相关依赖受影响时经[INDEX](INDEX.md)/[EVIDENCE](EVIDENCE.md)定位，不为恢复反复加载。
- [2026-10-28精简前STATE逐字节档案](state-archive/STATE-2026-10-28-before-completion-checkpoint-summary.md)保留所有旧基线/失败/现场；它是历史，不覆盖本页当前事实。更早状态档案、Prompt原文和来源继续保存。

- 最新计数证据：.cache/rogue-deployment-native-20261028-v2/verified-native-deployment.json（008e1f5e）；.cache/rogue-combat-stats-wire-20261028/{counter-archive-source-verification.json,counter-archive-checks.json,counter-archive-v3.xml,counter-archive-legacy-v4.xml,counter-related-v4.xml}。精简前STATE保留在state-archive/STATE-2026-10-28-before-deployment-counter-archive.md。
