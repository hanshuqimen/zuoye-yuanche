# 公开招募实施与验证

当前为开发实现，尚未完成公开招募的整体验收；不能标记成熟版本。

## 协议依据

冻结 CN Android 2.7.71 类型索引确认 `normalGacha` 对应公开招募，`advancedGacha` 对应寻访。
`SyncNormalGachaResponse` 和 `NormalGachaResponse` 继承 `PlayerDeltaResponse`，自身无声明字段；
不能据此省略父类型的增量。结束响应另含 `result`、`charGet`。

`PlayerRecruit.normal.slots` 使用字符串槽位键；客户端 LoadBuildData 遍历整数 0–3。
状态枚举来自元数据压缩默认值：LOCK=0、IDLE=1、BUSY=2、FAST_FINISH=3。
槽位字段为 state、tags、selectTags、startTs、maxFinishTs、realFinishTs、durationInSec。
selectTags 元素为 tagId/pick；pick 的显示行为由 BuildSlotViewModel.LoadData 核对。
ParseNormalGachaRequest 把配置界面的毫秒值除以 1000 写入 duration，因此请求单位为秒。

只读加载代码切片：`.cache/client-metadata/live-recruit-contract.bin`，
范围 0x39fef30 + 0xc200，页对齐范围 0x39fe000–0x3a0c000，SHA-256：
`e398842d4feb9e690df07cd07883112ec585372a7a51b8e8866330237cffc59f`。
没有修改客户端招募函数或错误分支。

## 已实现的状态和事务

- 版本匹配的公开招募目录由 recruitDetail 的六个星级段逐项解析，与 character_table 唯一关联。
  当前目录 160 名干员，各星级数量为 8/5/16/41/55/35；没有使用全干员名单作为招募池。
- 标签来自 gachaTags、职业、站位和 character_table.tagList；普通招募排除特别活动的性别标签。
- 时限和价格来自 recruitTimeTable、recruitRarityTable、tagPriceList。当前冻结表 54 档，
  价格全部为零；保留这个事实，尚待与自有客户端静态数据及显示行为进一步交叉核验。
- 前两个槽位按 0-2 通关条件开放；Progressed/Sandbox 本地预设允许使用初始槽位。
  后两个槽位、办公室生产标签刷新和付费加急尚未实现。
- 开始招募在同一事务中扣除许可与费用，保存种子、结果干员、保留标签、版本指纹和完整计时。
  结果在开始时确定，读取、重启、重复请求均不会重新抽取。
- 许可加急保存真实完成时间，同时保留原始最大完成时间和选定时限。取消不退款。
- 完成时检查时间、状态和版本；授予干员/重复信物，记录历史、发布任务事件并清空本次状态。
  幂等收据处理重试；不同序号再次领取也不能重复发奖。
- 新增迁移 0005_recruitment_state；旧数据库和旧备份沿用原记录升级，没有替换账号存档。

## 仍需补齐的业务

LOCAL_RECRUIT_V1 是明确标记的本地抽选策略：按候选星级分组抽选，优先保留可满足的标签组合，
不声称等同官服概率或标签脱落率。九小时高级资深/资深保证依据冻结 recruitDetail，
同时出现时优先高级资深。抽选策略与版本随进行中的招募持久化。

尚未推断干员入职的额外资质/高级凭证奖励。potentialMaterialConverter 用于信物兑换，
不能直接当成干员获得奖励。公开招募应提供资质/高级凭证和重复信物的范围，官方依据为
[寻访规则调整说明](https://ak.hypergryph.com/news/2023033352)；数量仍需明确依据和验证。

特别公开招募活动标签、办公室刷新配额、后两个槽位购买和付费加急仍未实现。
因此当前流程即使可显示或领取，也不能标记完整公开招募已经完成。

## 自动检查和真实客户端

20 项新增测试覆盖：协议槽位与开放条件、同步增量、消耗、非法输入、并发重复领取、
事务回滚、九小时保证、服务器重启、取消、备份恢复和 0004→0005 升级。
另检查导入引用和损坏存档的明确拒绝。完整回归 148 项通过，17.58 秒；新增/修改文件 Ruff 通过。
旧迁移测试的造库函数同步移除新增列，以保留真实的 0001 旧结构，未弱化生产迁移。

真实客户端验证使用独立副本 `.cache/refresh-diagnostic/recruit-oct09-v1`、端口 18443。
仅在副本中增加招聘许可和加急许可各 10，保留单独的 test-supplies.json 回执。
正式存档、原模拟器 index 0、官方资源和 APK 均未用于这些业务写入。
当前已实际通过登录、全量同步和主页刷新，正在按新手引导进入招募界面。
招募、计时、领取动画及重启后的客户端表现尚未完成验证。
