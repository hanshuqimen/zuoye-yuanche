# 危机合约 V2：任务币与商店币依据（2026-11-26）

当前源码已接原版 `confirmMissions` 的符文组0、挑战1及混合宝藏2批次。18项新币用例与受影响回归合计107个不同检查通过，冻结首季五图9份历史时间QA方案、162次真实HTTPS、冷重启与新目录恢复通过。尚未进行原版币弹窗验收，原生商店目录/购买和 `season.coin` 含义仍未完成；没有新EXE或全模式完成结论。

## 研究开始时的基线（保留原始过程）

接续已公开f3fc441（main6c262ff）的原版宝藏领取；该检查点807公开文件/754源码/390提交已匿名下载及项目内新目录完整恢复。本轮开始HEAD ecfa60c，工作区干净；其后两条提交为公开回执和归档换行修正，没有业务差异。完整目标保持，当前符文组/挑战领取仍明确501，没有开始发币或改现用存档。

冻结metadata实查：PlayerCrisisV2.shop为PlayerCrisisShop（字段16007），后者coin字段15957/int/+0x10、info/+0x18、progressInfo/+0x20；PlayerCrisisV2Season.coin为字段15977/int/+0x10。这只是结构，不能直接推出两个数字都应增加。EntryViewModel.coin字段222802/int/+0x60。ZoneEntryModel的旧索引部分offset为16843010xx异常值，不据此做字段读写。先前候选M163070实际是返回float的UI进度getter，不应按名字当作赛季金币依据。

四个明确消费者候选：M162956 RefreshPlayerData、M162957 InitServerData、M190300 InitData、M190301 ApplyServerData。冻结ELF完整SHA核对后，其默认体共4088字节均可线性解码，序言与完整边界记录于本地；线性解码本身不证明含义或活动Hotfix一致。已构造四页有界REA输入，SHA-256 `3cf79c8aba571bdc4ff23936071a0be22d2c5f7ef89248061fc99a8073b2970f`，未知调用仍无伪造实现，REA自有stdio会话83384已实际ready/open成功，清单生成的四个入口正在分析。

证据`.cache/crisis-20261119/coin-contract-20261126-v1/{metadata,body-probes}.json`、`rea-coin-contract-20261126-v1/static-methods.json`及`mcp-coin-contract-20261126-v1/`。本阶段未启动模拟器，不读玩家堆、官方/浏览器认证或活动Hotfix。下一核原版消费路径、具体首季/临时图奖励的isTimeLimit与窗口，再设计可与既有本地商店核账共存的事务；不能仅修改余额使测试过关。


## 四处消费结果与后续保护页

四处4088字节REA均成功，83384公开close成功/子进程与包装器实际退出0、分析文件保持，当前无该会话遗留。M162956/957和M190300/301通过PlayerData.get_data后的+0x100→+0x20→+0x10链读取币，分别写EntryViewModel.coin及ZoneEntryModel.set_shopCoin；元数据字段17818/16007/15957确认该链为crisisV2.shop.coin。主页/终端显示余额有依据，赛季coin用途及官方后台增减算法尚未由这四处证明。

进一步商店候选M162904/M162908/M162911/M162914在冻结体分别只解码8/324、0/508、0/168、4/1264字节；整组有界准入拒绝，v2未启动REA，不拼填充/假函数。核对已有已完整验指纹的五页capture，0x412f000已覆盖前两处全部832字节，均完全可解。该页原采集时GameData14457902、硬件/同shell进程/源保持已核；不再启动模拟器，v3重用一个来源的一整处函数，新的自有stdio会话65946受控启动。后二处0x4130000目前没有匹配已采页，缺口明确保留。

证据新增consumer-bindings.json、shop-body-source-probes.json、rea-coin-shop-20261126-v2/failure.json和rea/mcp-coin-shop-loaded-20261126-v3。当前未发币、未接未知商店成功响应；下一核真实入口/DTO，再结合具体限时奖励规则推进。


## 真实商店路由与临时图规则缺口

v3两处832字节分析及public close成功，65946实际退出0。SendGetInfo引用0xc0aa190→0xc60e8c8→0xa000cf99/literal26572，恢复为crisisV2/getGoodList；请求为无字段CrisisCommonGetShopDataRequest（1803），MsgBundle类型绑定、MethodSpec289721/SendRequest及泛型实例14524共同指向CrisisCommonGetShopDataResponse（1809）。响应字段为permanent、season、progressGoodList，不能仿照地图getInfo返回info。尚未提供该路由的假空成功响应。

首次把literal行当明文被边界检查拒绝；改用此前已有版本固定的定义/内容0或0x66变体，并以实际原版confirmMissions/literal26571作正控制。额外旧SQLite交叉核对又因两literal（含该已知正控制）均缺行而拒绝。实查不是冲突，当前索引这类覆盖不全，不能当作新证据的裁判；保留shop-route-index-disagreement.json。最终shop-route-bindings.json记录旧交叉核对不可用，只把冻结字节/唯一候选/已知控制/具体泛型绑定作为依据；未修改原metadata或旧索引。

首季四临时图确实各含三挑战，样例同一挑战同时有isTimeLimit=true的兑换币100，以及isTimeLimit=false的GOLD/4001/5000；首季永久挑战兑换币均不限时。stage仅有startTime和rewardEndTime，现有battle admission已明确不把rewardEndTime当关闭时间，本轮没有按名字撤回该正确安排。限时币资格、非限时奖励的晚领取和赛季coin累计语义仍需原版消费者核对，不能从空列表或字段名推断。

为补缺少的0x4130000，35214只启动既有index1、校验同版本APK/资源/数据/硬件/TLS/离线，绑定不监听的宿主端口，无API/玩家交易/回调写入/界面输入。一次读取4096字节，SHA-256 81edef0111605240d6ae7db6582bb343028dbab87a43e49f2d20cc8abcc69d27，两个候选体均完整可解；同shell硬件/包PID/启动ticks守卫保持。实际退出0，index1关闭、index0/来宾自有回调/现用和QA存档保持。该采集没有读取玩家堆或官方认证。

新有界REA混合输入为该单次采页中的162911/162914与冻结默认162614/162615（GetTempState/GetStageTempState），四函数2276字节、两页；每函数仍为唯一来源，不冒称整进程快照。自有stdio15018启动中，等待实际结果。证据loaded-coin-shop-callback-20261126-v1/capture.json、rea/mcp-coin-callbacks-temp-20261126-v1及reward-windows.json。没有新发币或重复原版领奖。

## 已收齐的消费者与到期边界

上段等待状态已结束。实际completion在 `.cache/crisis-20261119/mcp-coin-*/`，不是带额外 `rea/` 的路径；恢复时旧50473句柄已不存在，随后读取四份实际completion确认子进程0、public close成功、输入保持，没有因错误路径或旧句柄重开会话。前四批14函数/9900字节的汇总已存在并核对。

新增四处默认体M162604（任务可领/全部已领）、M163914（限时物品Render）、M163982/163984（两类商店可购量）共3016字节、四页，REA62804实际退出0、public close成功、输入保持。五批总计18函数/12916字节；原始伪代码仅本地。新容器SHA-256 `0e1f7ead5dc1cb9bd8aa6e79932e896e37124c87c13bfb6fd7ecdce9c11b9b35`。

- M163914在 `rewardEndTime-now<=0` 且 `isTimeLimit=true` 时隐藏物品，其他奖励仍显示。将此显示截止用于后台发奖是明确的本地策略，不称为逆得官方后台算法；原有当前赛季/地图开始时间的本地日历政策保留。
- M162604依据任务状态1/2计算可领和全部已领，未按到期清掉挑战资格；M163248/253/254也保留该状态。因此临时图到期后不能整批拒发不限时GOLD、CARD_EXP或MATERIAL。
- M163986使用 `shop.progressInfo[id]` 的count/order，M163982/984按order选择商品档位。`progressGoodList`应称进度/分档商品明细，不能据名字称为累计赚币里程碑。未据此伪造任何目录、价格或里程碑奖励。
- 已核入口/终端余额读取 `crisisV2.shop.coin`；`PlayerCrisisV2Season.coin` 的业务含义仍不明，本批保持原值，不向两个字段同时加币。

新证据在 `coin-contract-20261126-v1/{reward-consumer-targets-v2,reward-body-probes-v2,next-consumer-targets}.json`、`rea-coin-reward-render-20261126-v1/static-methods.json`、`mcp-coin-reward-render-20261126-v1/`。本批未新增Android读取、界面输入或战斗。恢复核对中的两次不存在路径（domain/runtime.py和cache/gamedata）均为只读定位错误，没有更改输入或绕过检查。

## 原版任务批次、余额与旧存档

新增纯奖励解析组件 `crisis_v2_mission_rewards.py`。模式0只接有实际成员和非空 `slotPackRewards` 的永久指标集，模式1读取匹配地图的 `challengeNodeDataMap.rewardList`；两者均要求本账号已通关且该任务状态1。支持匹配物品表的CRS_SHOP_COIN_V2、GOLD、CARD_EXP、MATERIAL，兑换币ID还须等于本版shopCoinId。未知类型、错ID、空定义、未完成/已领、未开放、关闭赛季均明确失败；全批先解析再写入，没有部分成功。到期挑战只过滤限时条目；若全已过期，返回冲突并保留未领状态，不发空成功。

币直接计入已证实的 `crisisV2.shop.coin`，不经普通仓库。其他物品使用既有事务发奖；状态0/1对应runePack/challenge改为2，混合宝藏保留旧资格/材料包策略。新增币批次使用 `cn-2.7.71-crisis-v2-native-missions-v2`，旧宝藏v1的绑定摘要、回执结构和原答复保持；跨seq/重新登录/冷启/恢复读取首次奖励和时间，不重发、不回放旧增量。不同批次重叠已领任务整体冲突。

余额恒等式为“密封原版任务回执入账＋显式本地商店信用－显式本地商店消费”。本地配置目录、价格及信用政策仍独立标记，不能冒称原生目录。新领取、商店读取/购买、启动及恢复都核账；现有本地账本按原版回执总额扣除后核对原有配置，允许其消费原版任务币，保留旧账本和指纹。只查询本账号任务前缀，不扫描其他业务回执。损坏响应、资格标记、余额或删除全部入账回执在写启动前拒绝。

## 实际验证及失败保留

18项新用例包括混合delta/批次倒序、跨seq及重叠、期限前一秒/等于期限/之后、错奖励与假币ID、未完成/未通关、未来图、账号隔离、并发、写后回滚、分批入账及耗材后旧重试、本地商店消费和新目录恢复。连同既有宝藏、共享领奖、备份恢复、保存准入及原版战斗相关回归，当前107个不同检查均通过；Ruff检查/格式通过。

首次运行因未先创建basetemp父目录而40项setup错误，业务未执行；v1输出保留。第二轮39过/1失败，失败为QA调用本地claim-credit时只传seqnum，而该本地接口要求idempotency-key；修正测试请求后该项单独通过。随后有针对性的70项回归实际退出0，没有为补记录全量重跑已过用例。既有Starlette/httpx弃用警告保留，不改依赖掩盖。

冻结14457902当前仅导入首季 `crisis_v2_season_1_1`，现实时间已关闭，使用独立QA历史钟。永久图11个符文组/挑战一次批次入账2400；四临时图各3挑战，开放方案各入账300，到期边界各入账0而普通奖励仍发。共9份方案，在三次有序服务组中完成162次HTTPS，逐次delta、同seq/新seq、冷启和真实备份的新目录恢复一致，实际38418退出0。所有资格为QA预置，不是自然战斗结果；没有改现用存档或重打关卡。原家具原生QA数据库以只读preflight通过，冻结表与该旧数据库SHA保持。

本地证据：`coin-mission-tests-20261126-v1/v2/v3/`、`coin-mission-regressions-20261126-v1/`、`coin-missions-frozen-20261126-v1/verification.json`及`coin-missions-summary-20261126-v1.json`，均位于 `.cache/crisis-20261119/`。可重复入口为 `tools/verify_crisis_v2_coin_missions.py <冻结缓存> <新的项目内输出> --legacy-save <只读旧QA数据库>`。

下一先保存新公开回滚点，再做一个新的原版币领取代表；随后继续season.coin、匹配原生商品目录/购买、旧季资源与原版战斗结算。其余赛季、原版币弹窗、新Windows发行、完整离线和长期稳定仍未完成。
