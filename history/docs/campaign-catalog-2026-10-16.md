# 剿灭静态目录、版本校验与协议边界

本阶段增加剿灭静态目录及导入预检，没有接入原生剿灭开战、结算或周奖励。集成战略、卫戍协议、危机合约及其他完整交付目标继续保留；不能据此标记剿灭已可玩。

## 冻结数据与独立候选

新增表来自与现有扩展表相同的[不可变campaign_table](https://raw.githubusercontent.com/Kengxxiao/ArknightsGameData/a550f5e048bb94e7cdefc6eb97a4091f0c4c7add/zh_CN/gamedata/excel/campaign_table.json)。[版本文件](https://raw.githubusercontent.com/Kengxxiao/ArknightsGameData/a550f5e048bb94e7cdefc6eb97a4091f0c4c7add/zh_CN/gamedata/excel/data_version.txt)85字节与基线逐字相同；同revision的stage/item/zone/constants四表canonical指纹分别与当前缓存一致。36条campaigns均引用现有CAMPAIGN关卡，突破奖励的物品及家具引用通过。公开表与客户端FBS全值一致性仍未证明。

- campaign_table原文440791字节，SHA-256 `9d667bbaf1cd67dabd5e47a033918c02d65e54bedae357913d60d320d19e07e9`；canonical指纹 `957ff45799346b63ba30c902bb7d8f72ac7ae1b4155b5c39b382b5300e0194ff`。
- 独立候选GameData为 `f4ef9ba642138521ac84a16943b72a4f31a7c74d48417f017c314a9d729ae219`，19张表；旧18张指纹全部保持，diff只有campaign_table新增36关卡及相关配置。
- 候选保存在本地 `.cache/campaign-prepare-2026-10-16/imported`，没有激活、改设置、迁移存档或扩大客户端兼容配置。现有f441基线和已验收EXE保留。原文和GameData不提交源码仓库。

## REA静态依据

复用冻结CN2.7.71索引、元数据和已有文件映射代码；本轮没有重装REA或伪称不可用的native provider已经运行。证据集CAM-DECL/CODE/HOLDERS/TABLE-20261016在 `.cache/rea-2026-10-16/campaign-contract`，含REPORT、来源摘要、逐字段比较及66份相关证据。T/F/M编号是冻结索引引用，非REA服务器签发的Evidence ID；未以静态结果代替实际HTTP请求。

CampaignTable及相关目录、梯度字段与冻结声明匹配。M30581从gainLadders末项逆序返回最后一个killCnt<=输入的项，M30589把DEFAULT六个整数置零；108组gain列表全部升序，其中69组非空。本次代码据此保留表序并向下取档，无匹配返回该全零默认；displayDiamondShdNum仍是展示值，不作为精确合成玉实际收益。

PlayerCampaign有七字段，包括current/total、open、missions、instances和sweepMaxKills；周面板直接读同步值。匹配全局initCampaignTotalFee=1200，但服务端累加、截顶、刷新和精确奖励分布尚未闭合。rewardStatus在达到击杀档后以正值表示已领取，不能写入UI的三态枚举。

CAMP_*默认载荷提供campaignV2独立开始/结束、扫荡、突破领取和额外任务领取路径；开始的Campaign类型泛型已绑定。实际route literal仍受保护，结束数据编码及原生HTTP尚需验证。扫荡使用CampaignFinishBattleResponse，不能复用普通quest响应。原生结束和新版周面板还需有界文件映射页0x3120000/8192B及0x43D0000/4096B，当前未为此启动模拟器。

## 导入和查询实现

新增可选CampaignCatalog，校验关卡种类、严格升序梯度、退款不超关卡费用、整数及奖励类型、家具等引用、分组、区域、前置与时间窗口。GameData按campaigns根计算关卡数并提供差异；缺表时明确503。目录对象和梯度使用不可变记录，查询不创建战斗、不扣理智、不发奖。

版本表中存在四条历史训练引用：group_tr_37/38的camp_r_7、group_tr_39的camp_r_9、group_tr_40的camp_r_8，不存在于campaign或stage字典。第一次严格导入因此被拒绝，失败证据保留。现在只对上述完整canonical表指纹及精确配对记录已知缺口；不改原文、不补别名、不把这些条目当可玩关卡。Catalog公开unresolved_training_references，调用相应training_stages分组返回明确503。任何表内容变化都使这份特定例外失效，新未知引用仍拒绝。该处理是本项目对冻结数据缺口的兼容策略，不是从原生实证得出的自动修正行为。

59项静态目录/数据导入专项检查、977项完整检查（227.64秒）和Ruff通过，只有一项既有弃用警告。涵盖边界取档、全零默认、类型/引用/退款错误、家具、损坏目录、不可变导入/差异/重开，以及已知缺口不能成为可玩别名、不能覆盖新表。测试数据全部人工合成，没有提交官方表。候选19表的真实验证与上述合成检查分别记录，没有把导入通过当原生玩法通过。

后续取得上述最小代码页与真实开始/结算请求，完成独立campaign领域实体、事务和七字段同步，再验收低档、400击杀、突破/额外任务、周上限、训练/轮换、扫荡、重启及原生视觉。候选数据存在和自动检查通过均不替代这些结果。
