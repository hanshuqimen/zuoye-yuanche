# 商店非票券收据与购买后合同

当前已进入[显式藏品获得与费用历史接线](roguelike-cost-relic-acquisition-2026-10-26.md)阶段，e392后端/215检查/冻结34HTTP与恢复通过，原生仍待验。下文为先前阶段的基础/失败历史，不覆盖新报告当前状态。

完整私服目标保持未完成；不恢复剿灭、不重玩旧关卡或招募。本轮完善将来收藏品购买所需的付款/库存/票券序号基础，仍未启用收藏品商品、实际发放或原生减费，不能标为收藏品购买已完成。上一目标轮次为实际进展：3cec748费用顺序模块/私有字节回读和新D恢复已有依据；本轮继续它的实际获得前置，不重新定义最终交付范围。

## 版本和范围

固定CN Android2.7.71、19表e915675d8d8a1cc97df8fa46eed27ef1bdaa9d1b0fdb07461dcabda36271ae29、rogue_1/NORMAL/0。具体关卡不适用，本轮是非战斗商店/代码合同。费用四效果与开放/各自解锁核对继续见[费用报告](roguelike-recruit-costs-2026-10-26.md)，不能因主题已开放推断收藏品已解锁。仅index1/<test-transport>/<test-device>；8秒命令/硬件/APK/资源/GameData/TLS/离线守卫保持，index0未操作。

## 源码及真实验证

业务SHA `76225112f3fa828cd23bc2003f9ba3cea035291142f79727ff0fa3c544c88d63`，schema0033/74表。Shop.ticket_indices从已导入物品类型编译为不可变集合，不来自客户端请求；旧报价payload和digest没有添加字段。当前接纳的普通、FREE、THIRD、DIRECT、晋升报价仍全部是票券，收藏品完整发放适配器未完成，编译继续拒绝四种RELIC。

纯付款引擎的Purchase.ticket允许无票券None。重放按票券类收据数量连续分配序号，非票券不占位；付款/库存仍按原购买tuple顺序重放，包括同秒和调时。严格拒绝错配种类、票券缺号/跳号/bool、重复购买槽位及不明确分类。补一处实际事务守卫：以后如果编译器先扩展非票券而发放适配器缺失，动作明确501并回滚余额、库存和收据，不能创建null ordinal票券或只收款不发奖。新合成混合报价仅为纯引擎检查夹具，不是已接纳的GameData商品或官方购买流程。

本轮最终103个不同检查：18新（17纯收据、1实际HTTP失败注入/完整DB回滚），85相关旧检查（普通商店/直升/精英/商店结算）。首次50项中49通过；新回滚用例误把error对象与字符串比较，产品已正确返回501/code。修正为error.code后只重测该项，含末尾全部数据库行相等断言通过；没有重跑原49。另53受影响分支通过，5修改文件Ruff通过。103是三次执行合并去重后的最终范围，不是单次全绿或全游戏零bug证明；FastAPI/Starlette弃用和既有Field alias诊断保留。

新的D目录receipts-new-d-reopen-v1用当前源码Runtime只读核对已有实际保存：完整rlv2与全部74表相等，14份旧商店报价保持有效并得到全部票券分类，124保护输入保持。没有在原保存启动Runtime或写入GameData。没有新schema迁移、客户端UI/动画验收或EXE；没有为了补记录重复已经通过且未受影响的费用纯模块/原生流程。

## REA购买后默认链及未解部分

冻结metadata确认RoguelikeShopActionResponse（T2092）没有声明专属字段；这不意味着HTTP没有公共playerDataDelta，也不能从其他版本示例加领奖字段。REA M154947/0x3f16640（440字节）的默认购买回调检查对象后，交给PendingEventHandler.HandleWhenShopBuy，再刷新商店状态、NPC对话和ShopStateBean。证据ev_7af2efdd，静态页ELF SHA `35c898ef4f511b7c6aba75aba6597af257e3ed51a4ff28a36c9d65ff312a5a4e`，26完整种子；Hotfix/全局重叠/PIC和不可达块警告保留。

首次混合静态采样被守卫拒绝：M152353 Render仅4/632字节，M153881 HandleWhenShopBuy为212/212；未启动失败样本提供器，rea-costs-pending-static-v1和诊断保留。新的独立0033代码副本先核对74表/完整rlv2相等，再仅读0x3e7d000、0x3ed7000各4096字节，SHA分别d40529ed19b8b987d5f01bb9cbe6949cedd3c6aafe134b4be11e3cdbea7e1294、0bffa299ea6a848efd2f48229bbf8baec585ed4eed8e31acbefb6f75b9698e9e。无堆/凭据/官方认证，动作白名单只有status/read_code/stop，0游戏输入/0rlv2/0战斗，5配置请求200；只有local_sessions变化。代码观察使用69822639业务基线，不能说7622已经原生验收。

两个完整方法的页ELF12288字节SHA `b0909db7595e7d8840d265bcb29d3a6fbaa55c4a85fb4d813c53d3fbc0d881ad`、40完整种子。M153881默认先尝试TryProcessTicket（M153845）；后半控制流有bad-instruction截断，所以尚未证明非票券购买的获得动画/事件完整合同。M152353（ev_3d7ce819）是图标缓存/选中显示，未读出layer语义，不能把这个方法说成层数消费者。对应Handle证据ev_989e6342；没有据此补默认layer/count或虚构pending事件。

REA两次观察分别先在45秒pending，原调用58.406/53.297秒成功，均未重排/重启。原生17682、REA87249及69048均实际exit0，两个公开close均成功，当前所属PID20948/21248/33120/35140/18448已查缺席，工件SHA保持。所属服务/ADB/index1正常停止，index0保持；先前cleanup_incomplete失败历史不被这些成功覆盖。

## 可重复的下一步

优先解析M153881截断处的实际指令/目标，并查具体详情消费者M152601 RelicPart.Render的完整性；M152353不再当layer依据。核对count/layer/获得事件后完成四收藏品实际发放、所属节点/购买顺序重建费用上下文、结算收藏品计数及一次新的获得/减费原生代表。保持旧报价与票券序号、事务/账号隔离/重试/重启恢复；不重打旧关。不用纯收据或HTTP501防线代替完整购买/视觉接线。

本地证据均在.cache/rogue-costs-20261026及.cache/rogue-costs-code-20261026-v3，原始官方表/metadata/代码页/反编译/DB/日志仅本地。最近完整私有回读仍3cec748/上传09d8a2ff；本轮7622尚未在该包内。已保留旧源与所有检查点，后续实质功能检查点再保存新增源码，不为记录自身重复打包。

2026-10-26四费用藏品显式获得：e3927b76/schema0033/74表，报价明确无叠层，真实shopAction发放、独立序号、因果费用历史与结束计数接入。215不同检查（22新193相关）、冻结四件34HTTP/每次delta一致；旧1–12/74表既有行/124输入保持，Runtime/备份/新D完整恢复通过。REA补齐默认购买尾调用和详情layer显示；53644实际exit0/公开close成功。尚未原生，0新游戏输入/战斗；官方自然资格/价格/图鉴/其他家族及全交付未完成。[报告](docs/roguelike-cost-relic-acquisition-2026-10-26.md)。
