# 危机合约零分首通与纪录更新（2026-11-28）

本轮修复首次零分通关没有建立单次纪录、没有更新纪录标记的问题，并处理同秒或回拨时钟下的新纪录缓存失效。完整原版后台、全部模式和成熟交付仍未完成；本报告的接口检查不等于原版游玩通过。

## 客户端依据与实际复现

冻结2.7.71的M162601 GetPermanentMapTotalScore（400字节）读取PlayerData.crisisV2.seasons[seasonId].permanent：state=false时返回-1，state=true时求和scoreTotal，空表合计为0。M162600 GetRankByScore（304字节）从列表末端向前，选择第一个不大于总分的阈值；本批未给未核枚举值补标签。48046实际退出0、public status/close及主体/入口/输入SHA已核，没有Android或玩家读取。

因此，“尚无纪录”和“已通关的0分纪录”在客户端中不同。修改前7a16e96的真实HTTP入口在两个独立人工数据档中均返回200、写state=true和六维0，却保留newRecordTs=0、isNewRecord=false。修改前两项回归实际失败，永久图为0!=1001、临时图为0!=1300；完整保存和首次响应留在本地，未改当前QA或旧游戏存档。

另核实际导入614abf4e的20表/S4、固定历史开放时间1755182228：当前开放临时图crisis_v2_01-03_b（stageId level_crisis_v2_01-03）及永久图crisis_v2_04-01（level_crisis_v2_04-01）不选指标时均为六维0。仅覆盖这两个实际开放配置，不从它们推定全部赛季、其他模式或原生战斗已经通过。

## 修改及兼容

新通关回执采用明确的local-clear-receipt-v2：第一次永久图通关即建立单次纪录，包含0分；临时图第一次通关也标记纪录变化。原版响应在新策略下把首次纪录显示为isNewRecord=true。已有通关的同分重复仍保留第一份单次纪录。

每次实际纪录变化将newRecordTs更新为max(旧标记+1, 当前服务器秒数)。这是本地缓存失效标记的单调策略；展示用的战斗ts仍为真实本地结算时间，不把逻辑标记当战斗发生时间。超过客户端long范围时在提交前拒绝、整笔回滚。上述选择是明确的本地后台策略，未冒称逆出了官方后台算法。

旧v1回执继续按原投影校验和重放，不重新计算其首次零分标志、时间、分数或首次原版响应；战斗预检、原版结算及日志读取同时接受已验证的v1/v2，未知版本明确失败。没有数据库结构迁移、源码分支重置、旧保存转换或新资源导入。

## 已验证范围

当前190个不同检查最新通过，其中11项新增；新10项首批通过，随后受影响180项有179通过、1份旧测试夹具失败。该夹具写了已有32分纪录却遗漏cleared=true，原版总分函数实际会视为无纪录；将其修为真正的已有纪录，并按v2更新标记预期后，仅复验该项通过。初始失败及全部JUnit保留，未重跑未受影响的473次TLS或原生关卡。

新增覆盖永久/临时零分首通与原版增量、同分保留、同秒/回拨时钟、新序列重试、旧v1日志/回执冷恢复、未知版本及标记溢出拒绝。Ruff通过。另把修改前真正由v1代码产生的两份保存分别复制到全新项目目录，新Runtime冷启和真实原版HTTP结算重试均200；旧通关回执和首次原版响应逐字段相同、原始57文件哈希保持。这里的“原版HTTP”指原版协议路由，未进行新的原版客户端游玩。

证据根`.cache/crisis-20261128/`：

- `mcp-season-score-20261128-v3/analysis-summary.json`及`season-score-contract-v1/body-probes.json`：两个冻结消费者和实际关闭。
- `zero-record-regression-v1/before-verification.json`、`zero-record-tests-before-v1/junit.xml`：真实旧代码复现和修改前失败；私有重试材料不入Git。
- `zero-record-tests-after-v1/`、`zero-record-affected-v1/`、`zero-record-fixture-correction-v2/`及`zero-record-check-summary-v1.json`：190个不同检查的实际范围及保留失败。
- `zero-record-legacy-upgrade-v1/verification.json`：真实旧保存新目录升级与首次响应保持。
- `zero-record-frozen-s4-v1/verification.json`：实际20表、具体地图、开放窗口和零分结果，未打开数据库。

原版滚动/购买/危机战斗、getSnapshot接线、season.coin、旧季资源、全部模式、最新Windows发行及最终离线/长期验收继续未完成。
