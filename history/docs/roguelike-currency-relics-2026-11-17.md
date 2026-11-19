# 即时希望、容量与源石锭藏品

完整目标ACTIVE未完成。当前10种即时资源效果已通过源码/接口、261项相关检查及正式41用户78表恢复；自然供给、此批原生及新EXE未完成。QA40部署通过/技力读数未验，基线见[原生记录](roguelike-global-witness-2026-11-17.md)；不再开关追同观察。

实际19表e915/v077/77.6.0、client_verified=false，限定rogue_1/NORMAL0/1792645099（主题已开始/已归档）；不是与CN2.7.71/V070全表同版。43个含immediate_reward的定义中40为RELIC、3为BAND。当前9种已有完整接线=6编队容量+3立即源石锭；rogue_resource_relics实际是按源石锭分层攻速，不能因名称误算成即时资源能力。

新候选10种的全部效果仅为即时GOLD/POPULATION/SQUAD_CAPACITY：m17增加11源石锭/3希望；q01增加2希望/1容量；q03/q04各4希望/1容量；q06为6希望/2容量；r06/r07/r08各4希望、r09为6希望、r10为8希望。逐项全黑板、条件、物品类型和实际目标引用/常量已核，不只处理混合物的一半；档案均非特殊/无登记时点。解锁描述仍不是自然供给资格证明。

其余21个含即时奖励的藏品仍另待核：r01..r05五种涉及生命、r14..r24十一种发晋升券，a45/q02/q05/q07及n02五种附带部署上限或改关效果；不能因为也含immediate_reward就只发一个资源而称完整。当前能力仍107/245，十候选只有实现并验证后才计入，不自动加入21默认基础自然池。

计划用独立完整定义目录与不可变资源增量，经显式商店/战斗奖励、因果回放、发现与终局准入接通。源石锭在报价支付顺序内只记一次；希望总量变化须保留已消耗希望，容量峰值同步回放。旧目录/旧报价摘要、旧保存及默认供给保持，越界/重复/未处理招募/错误完整定义拒绝，任意投影失败整事务回滚。成功仍需正式表及完整40用户恢复核对，不以HTTP200或数量当原生证明。

只读审计audit_immediate_scope实际exit0、0新Runtime/存档/Android：.cache/rogue-immediate-resources-20261117/scope-v1.json及source-contracts-v2.json保留完整本地依据。早期把汇总整数字段当列表读len导致TypeError、一次仅搜Immediate类名为0，均不是无实现证据；后按真实定义/目标物品分类，取得11个资源/属性metadata候选，尚未把候选当函数行为。官方表/完整反编译/日志/保存不进Git。

## 当前源码和检查结果

业务dc85fe68b1c35954be2835fccee9e62c26f9a805a9ed88e3389b81c19cc04659，204个Python、schema0037/78表。独立rogue_currency_relics冻结全部10定义/条件/类型、三个资源常量和具体目标引用；从真实黑板重算每个分量并核对不可变增量，防止把混合奖励漏成单一资源。档案特殊/登记标志拒绝未审配置，目录摘要绑定档案及全部增量。共享resources_after_relic供商店提交和全历史回放/战斗领取使用；商店源石锭已纳入先扣价后授奖的逐笔余额，不二次加钱，希望总量与容量同步原子提交、保留已花费希望并记录容量峰值。

新显式报价单独绑定CURRENCY_POLICY及目录摘要；旧报价无新类时不引入新依赖。战斗奖励编译、因果唯一库存、发现及终局准入接同一完整能力，未知生命/晋升券/混合战斗效果仍拒绝。117/245仅为当前完整效果能力并集，尚有128种RELIC完整效果未接；本即时类别当前19/40，21剩余条目不因分类而实现。旧49属性目录/42全局目录、既有报价与21默认基础自然池不扩，不宣称官方出现率、售价或解锁资格。

27个新检查通过：十条真实完整向量、关键字段/条件/资源引用/额外效果篡改、特殊/登记拒绝、服务端向量漏分量拒绝、旧报价稳定/新报价绑定、十种购买的全部资源与增量/同新序号幂等、双Runtime并发一次付款一次混合发放、授物后投影失败全表回滚、后续容量越界无部分付款、显式混合奖励/重启及真备份恢复。234个相关旧检查最终有最新通过结果；合并XML按用例ID去重261，不累计重跑。12文件Ruff、204AST及diff检查过。

失败保留：targeted-v1的27失败均先卡在合成表缺gameConst；补完整合成版本引用，现有训练驱动明确用test_gold，测试单独绑定该合成配置/摘要，不放宽生产常量或冻结数据。targeted-v2的27过。related-v1为233过/1旧能力预算107断言失败，改成新增十项后的117，只补该用例budget-v1过，没有重跑233。首轮两处Ruff导入排序提示已修，Starlette/httpx及Pydantic alias警告保留，不当零bug证明。

## 正式数据与真实保存

verify_matched_v1/55993实际exit0：从QA40最终保存新D副本先核40完整用户及78表每一行一致；正式e915在1792645099编译10显式报价和8/2两奖励组，并确认全能力117、21其余即时效果全部拒绝。没有给物/新账号/探索/战斗。40完整用户78表在真备份恢复、冷重开和再新D恢复全部同，27肉鸽/0普通战斗及旧输入保持。

verify_actual_v1/26787实际执行45HTTP200，仅新增Vanilla QA41/一次探索，所有成功增量核同。在明确两层QA配方的首层行商逐个购买全部10，先扣每件1源石锭再授完整资源；每件同键和新键重试均不重复获得，库存唯一count1/layer0、发现state2、永久干员不因此改变。总额外增量11源石锭/45希望/5容量；随后购买1张普通券并正常关闭，离开行商推进第二层，始终0战斗。报价/配方均明确QA来源，不是自然供给或官方价格。

该脚本误把giveUpGame当成最终确认，45请求后断言失败；实际保存已合法ABANDONED/待确认，资源为gold6/hopeMax51/hopeCost0/capacity11及11库存行。**修的是验证步骤，没有修改产品关闭合同，也未重建账号或重授十件。** 原actual-v1副本/脚本/45请求保留；在新actual-v2复制此待确认41用户保存，按既有关闭合同只提交gameSettle及同/新键重试3HTTP200，确认SETTLED/账本存在、当前玩家空、资源不重复。

resume_actual_v2/75885实际exit0，合计48HTTP200。41完整用户78表在真备份恢复、冷重开、再次新D恢复严格同，原40完整用户/27旧肉鸽战斗及全部旧行保持，当前仍27肉鸽/0普通战斗。finalize_verified_v1实际exit0核全部保护输入/204源码不变。0本阶段Android/新原生/战斗/EXE；不拿API或源码通过冒称玩家操作此批已原生验收。

权威.cache/rogue-immediate-resources-20261117/final-v1/{verification.json,final-checks.json}，matched-verification-v1/{verification.json,full-users40.json,restored-new-d}及actual-v2/{verification.json,full-users41.json,restored-new-d}；所有失败原件、scope/完整定义/原始保存/本地会话仅.cache，不进Git。新私有源码回读检查点下一执行，完成前最新已验远端仍ef90050→d28fdea；此后继续生命/晋升券/部署混合效果及全部完整目标，q21读数缺口仍保留。


## 私有源码检查点已实际回读

2026-11-17 即时资源源码私有检查点完成：sourcec9b83507352b178ce23ef6d7007aaaddab64b6c2/业务dc85fe68b1c35954be2835fccee9e62c26f9a805a9ed88e3389b81c19cc04659/204Python/0037-78 → private7aa0a46697c4f9b6aabc46e10524f429315d253b，父d28fdea1376064ac6f4cfee6c9089a100c439e62/treedb5a397091862ec31b5f30dc677f0434fa712244。bundle 2984043字节，SHA256 52aa6ead1b4a13b2b9e2aa7c7428eb7268dc413385dced6ff301556fdc1c6410，Gitblob 58661b46cfb34cc8bedf8bc8ef464b2fb52ac681。642当前文件、317完整提交；644历史路径3542 UTF8 blob扫描未含禁入文件或凭据标记。旧255非README项保持，README新1741字节范围前缀及旧176050字节全文后缀，远端258项。私有/ref/父/tree、manifest和README完整实际回读同。

普通Git禁交互probe实际exit128，无可用登录；连接器expected_sha+force=false续private main，未伪称源码分支push。二进制fetch/fetch_blob分别UTF8限制/解码失败；IAB最初已退出登录呈404，用户自行登录后，精确提交Download真实事件入站。verify_remote实际exit0，下载SHA256/Gitblob双核、新D完整tree/blob/Prompt/fsck/clean及317历史严格同后才轮换heartbeat-latest/local-latest。仅本次新C临时下载移D；不读密码/验证码/浏览器凭据、不改权限、不访被阻止8080。旧索引previous-*、旧包、所有失败和发行物保持。完整业务源码和其余保护输入保持，索引授权轮换另有proof。

准备v1把最终检查汇总误当逐用例字典，先断言失败且未创建bundle；v2按实际汇总字段核对，不重跑已过检查。Node第一次对象输出被截断，仅显式JSON完整传输后才创建blob；两失败脚本/元数据保留，不拿失败输出生成包。实际准备62040 exit0、本地恢复及verify_api/verify_remote exit0。

范围含十种完整资源效果与261不同相关检查（27新）、正式19表/41用户78表真恢复、QA41一次明确QA探索48HTTP200/0新战斗，以及此前QA40新2_4部署SPAWN1/DEAD1、反编译/输入研究和失败原件索引。q21技力消费仍未证实，能力117/245、即时19/40不是自然池；本批原生、128其他完整效果/21其他即时项、所有模式/Golden/断网长时/性能/Harmony及成熟EXE未完成。下一生命/晋升券/混合效果按完整匹配合同推进，不重打旧关或恢复取消剿灭。

权威.cache/github-checkpoints/heartbeat-latest.json及currency-relics-20261117/upload-verification.json；prepared/old-remote/readme-preservation/pending-commit/api-readback-summary/remote-meta/received-web/restored-remote-c9b8350/protected-inputs-after-index-rotation.json均仅本地。此完成文字晚于源码包，不冒称已在包内，也不为文档再造重复bundle。
