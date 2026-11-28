# 危机合约赛季字段的消费者核对（2026-11-28）

完整后台和全部模式目标保持。本轮在被动输入计数正对照失败并正常收停后，转向尚未证明用途的`crisisV2.seasons[seasonId].coin`；不因商品列表未滚动而改余额、排序或游戏规则。

## 固定范围

原版2.7.71冻结ELF SHA-256 `3ece1e7b34165233fe8c3c919cf55dfcb4406b6bbc2725def2b1242b4c0a6259`、metadata `bf14421bbafe9c71d944ba4f97b31ecd666232640eac0829db3d84ac716ac8b8`由现行NativeTypes实际核验。当前QA仍为SDK3/S4/614abf4e的20表独立档，赛季4_1固定历史开放窗口；本次只核客户端默认消费者，不运行游戏、读取玩家对象或据此断言官方服务器的发币规则。三方法输入为冻结代码三页、20,480字节容器 SHA-256 `5836443dfa5cb4fc9e023650a66bbe0366e80893e7c689a5b31a7ad0c5366e34`。

元数据明确区分PlayerCrisisShop.coin/+0x10与PlayerCrisisV2Season.coin/+0x10：虽然字段名和类内偏移相同，拥有者不同。前者已有Entry/ZoneEntry读取与真实300币领奖依据，不能据此把后者也增减。PlayerCrisisV2Season的permanent为+0x18、temporary为+0x20，V2根的seasons为+0x18、shop为+0x20。

## 已取得的REA结果

实际92253退出0、公开status/close成功、输入SHA保持；每个结果核对主体SHA、方法入口和命名，三个不同函数共1,656字节：

| 方法 | 完整函数字节 | 实际可见路径 |
| --- | ---: | --- |
| M162939 GetViewModelForCurrSeason | 728 | 从传入PlayerSeason.permanent读取符文/评语等，并调用_LoadCommonData |
| M162940 GetViewModelForPassedSeason | 508 | 读取历史achievement的图名/图号/符文/评语等，同样委托_LoadCommonData |
| M163125 MapModel.UpdatePlayerData | 420 | 按当前seasonId查seasons，依地图类型选permanent或temporary，再更新任务、节点、背包和可用集合 |

这三层没有直接观察到PlayerSeason.coin读取，委托方法仍需核对，不能推广成全客户端未使用该字段或后台应恒零。Ghidra异常抛出路径的terminal-call限制保留；未知callee只加名字与上下文，没有拼造函数或成功实现。

PlayerSeason构造M29077冻结248字节、线性解码0字节，拒绝当作已分析。初次准备误导入不存在的META_HASH，在NativeTypes读取或输出前失败，核实实际常量METADATA_HASH后重试；失败单独保留。

后续_LoadCommonData/M162941冻结916字节全部可解，一页12,288字节独立容器SHA-256 `485d5d3013536644d5a8170b41846297f482a5a811d61dcbfda07bd6a98d8c80`。78257实际退出0，主体/入口、public status/close及输入保持已核。它读取玩家外观、称号、赛季开始时间及permanent的分维度分数；总分另委托M162601 GetPermanentMapTotalScore，再按M162600 GetRankByScore取评级。该916字节默认体同样没有直接coin读取，未证明被委托路径或活动Hotfix不存在消费。

本轮共四个不同方法2,572字节，未改游戏业务。下一精确跟进M162601及其实际数据源；不能用四个选定方法的阴性结果泛化字段无用、让coin跟随shop.coin，或声称完整赛季已经实现。

证据在`.cache/crisis-20261128/season-coin-contract-v1/{metadata,preparation-failure-v1,body-probes,consumer-bindings}.json`、`rea-season-coin-20261128-v1/static-methods.json`、`mcp-season-coin-20261128-v1/{rpc-0004,rpc-0005,rpc-0006,completion,analysis-summary}.json`。原始客户端代码与工具结果只在本地，公开仅有自有结论、范围和依据索引。原版滚动/购买、season.coin完整增减合同、其他模式和成熟发行仍未完成。

共同方法另见`rea-season-common-20261128-v2/static-methods.json`及`mcp-season-common-20261128-v2/{rpc-0004,completion,analysis-summary}.json`。两个REA会话均已实际收尾，不按旧live/PID继续输入；没有新模拟器、玩家或认证读取，也未为记录重跑203/473等未受影响的后台检查。

## 总分委托已核及后续

新M162601/M162600共704字节已完成REA，48046实际退出0/public status与close、主体/入口/输入保持已核。总分读取永久图state及scoreTotal，未通关为-1，通关后为六维记录之和；这条明确路径没有读取season.coin。评级逆序遍历阈值列表，取第一个<=输入分数的条目，不擅自给未核枚举0补语义。

这一区分揭示首个0分纪录被当成无变化的后台缺陷，现以明确v2策略修正并保留v1投影，[验证及范围](crisis-zero-records-2026-11-28.md)。season.coin整体用途仍未知，不因六个选定函数未读它而删字段或跟shop.coin增减。接着取得原版[getSnapshot绑定与消费者](crisis-native-snapshots-2026-11-28.md)，接口尚未实现；未知货币字段不阻碍继续补齐已确定的成绩展示合同。
