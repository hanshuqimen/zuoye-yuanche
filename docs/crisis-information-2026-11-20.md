# 危机合约V2：信息源、玩家初始化与同步

当前新增的是`/crisisV2/getInfo`、独立的账号/赛季/地图持久化及同步接线。开战、结算、解锁授予、商店和完整原生可玩流程仍未完成。前期冻结数据与REA依据见[原合同记录](crisis-contract-2026-11-19.md)。

## 已核字段与初始化

冻结metadata的字段token、JsonProperty无参构造和PropertyName setter共同确认：PlayerCrisisV2.currentSeason的JSON键为`current`，nextRefreshTs的键为`nst`，同步根为`crisisV2`。其他本批玩家赛季、地图、奖励、社交和商店字段未发现别名。先前报告里的currentSeason/nextRefreshTs是CLR名，不能直接作JSON键。证据`player-state-field-attributes.json`、`player-root-alias-payloads.json`及`player-state-wire-contract.json`保存在`.cache/crisis-20261119/`。

新账号初始化为零进度，不导入历史玩家delta，不授予通关、每日符文、挑战、领取或货币。信息响应、当前ID、客户端赛季表及玩家seasons记录使用同一绑定。跨季及调时只改变当前视图，保留已建立的历史记录。

## 信息源与时间政策

`crisis_v2_server_table`独立保存明确提供的info对象及来源，绑定基础GameData版本、冻结ELF和地图规则。导入要求匹配共享表，校验地图/符文/互斥引用和完整信息缓存字段。客户端使用的原始配置（包括showTip缺省）保留，不自动补值。

`shared-table-inclusive-end-v1`是本地服务器的明确日历政策：使用共享表的闭区间，并将end+1及地图日程作为下一刷新时间。它不是已获得的官方服务器日期算法。某个共享赛季当前开放但没有导入其信息时返回503并回滚，不把它变成空赛季；无活动赛季时current为空、info为null，与已核客户端空赛季缓存合同相符。

只读快照从数据库组装，getInfo使用现有事务和重试回执。重复请求返回原响应；新请求或sync推进时间视图。配置绑定在打开可写数据库之前核对，不自动转换其他GameData或信息源的旧存档。

## 存档迁移与当前检查

新增0038版本的三个独立表：crisis_v2_accounts、crisis_v2_seasons、crisis_v2_maps。从0037仅追加这些表；旧玩家行保持。更早迁移保留原来的步骤，新表创建也处于同一事务。旧备份仍按原版本读取，经迁移及配置核对后才发布恢复结果。

首批信息与计分51项检查通过。扩展检查首轮200通过、2失败；失败来自新增测试把Database误作上下文管理器，迁移断言尚未执行。改为显式关闭后，仅复验这两项，均通过。本阶段202个不同检查的最新结果全部通过，未声称新全量测试通过。覆盖并发重试、账号隔离、重启、时间切换、缺失信息源回滚、0037全旧行比较/失败回滚、独立备份恢复、配置变更预检及相关旧迁移/同步检查。

六组历史夹具在构造旧版本时移除这三张空表，拒绝移除已有进度；原来的旧表数量保持，迁移后的当前数量为81。没有把新空表留在旧夹具中来假造旧版本通过。

随后数据准备工具3项通过；审阅发现当前0038存档缺表时可能进入可写启动，已前移只读预检，拒绝三个表中的任意缺失或全部丢失，不自动补零。新增4种缺表情况和1项认证/意外字段检查，连同受影响的信息/持久化检查共23项通过，确认失败时未调用数据库初始化、主文件字节及旧行保持。本阶段累计210个不同检查的最新结果通过；原来的两项测试脚本失败保留，没有重跑全量来改写首轮结果。认证沿用现有事务入口和本地会话，空请求严格拒绝额外字段，不输出或记录token。

本地证据`information-v1.xml`、`information-v2.xml`、`information-migration-v3.xml`、`information-prepare-v4.xml`和`information-preflight-v5.xml`，失败与重试目录全部保留。定向Ruff及`git diff --check`通过。

## 可重复准备

项目工具`tools/research/prepare_crisis_v2_info.py`使用现有Python环境，把基础数据、同版本共享表和明确的info对象准备为新哈希目录；`--dry-run`只做校验。输出只在项目内，不选择配置、不打开存档，响应包装和玩家delta会被拒绝。正式运行仍使用已有`terralocal serve`；当前阶段只在独立测试目录验证。

## 冻结数据及独立HTTPS进程

从未改动的f441基础包准备独立20表包`14457902af1c44338067be0bec6f84272682e6fc9c938e25bf5c2359ebcedecb`，版本为v077/rel77.0、Change123576、VersionControl77.6.0。加入同版本crisis_v2_table及首赛季五张地图的信息源；共享表包含其他赛季定义，但本批只导入首季info。历史样本仅提取info，未导入playerDataDelta。新配置、全新Vanilla测试账号、固定游戏时钟和自有TLS证书全部在`.cache/crisis-20261119/real-information-v1/`，现用根配置字节及原数据包保持。

两次独立游戏HTTPS服务实际运行并正常退出0，共9次实际请求全部200。核对信息对象等于导入源、五张地图零进度、同seq重试及冷重启重试完全一致、同步保持。把独立游戏时钟推进到首季结束后，getInfo返回null，并用短键`crisisV2.current`发出增量；旧赛季五张地图记录保留。随后真实备份并在新目录恢复，保存数据及绑定匹配，恢复文件SHA-256为`2064ca2d5723aad4e3d540b465aee4e65d2a7eeb0146fe244aaca0200335ffc6`。

这9次本机HTTPS样本为15.520–57.837ms，首次getInfo为57.837ms；样本太少，不能据此声称普通API P95<50ms性能门槛通过。进程验证完成后才补上述只读缺表预检，以23项受影响检查核对，没有为文档重复运行HTTPS。

实际回执位于`real-information-v1/preparation.json`及`real-information-v1/https-verification-v1/verification.json`，均不收入Git。本批没有启动模拟器、使用原生危机合约界面、切换现用存档或重建EXE；profile的client_verified仍为false。开战、结算、解锁和奖励授予、商店、成就、其他赛季及完整原生流程仍未完成，下一按冻结REA合同接入BattleSession。
