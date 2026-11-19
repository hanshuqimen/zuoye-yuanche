# 肉鸽探索结束确认与评分（2026-10-24）

## 真实原生依据

v17来自1f591c3/86f37ddc，在新D副本使用v16真实失败的脱敏HTTP重放存档，没有再开战。原生“凋零残响”首页显示指挥分队、两名干员、迷雾歧途与藏品0；下一页实际发出空对象POST /rlv2/gameSettle，旧源码501。38请求37×200+1×501，错误类型计数空，不能抵消501。只有local_sessions变化；57其他账号表和全部保护输入保持。原执行句柄99955实际exit0，所属服务/ADB/index1正常关闭。

这是重放夹具的结束界面消费证据，不是第二次实际战斗，也不是原始密文重发。计时使用固定QA时钟，首页历时文本不完整，未计完整计时验收。

## 已实现与来源边界

新增独立rlv2_game_settlements账本、SETTLED终态、schema0025/71表及空请求gameSettle。仅当前已接纳的傀影NORMAL/0、基础指挥分队、第一层普通战斗账本自然失败分支：从保存的节点/战斗/招募统计生成结果，分数、蜡烛、灵感、外部关卡计数与结束状态同一事务提交，清除current并保留原战斗/失败归档。相同或新seq重试读取旧结果，不重复增加余额；新探索活动时不误重放旧结算。

七项权重来自[PRTS傀影主题评分说明](https://prts.wiki/w/傀影与猩红孤钻)，是**版本化社区规则适配**，不是逆向出的官方服务端公式。当前将保存的到达节点（含最终失败节点）计入步数、成功普通战斗计入普通作战；这两个口径仍需官服依据对照，不能用自制响应原生显示证明数值与官服等价。分队不计收藏品；第一层失败不计完成一层。评分明细顺序为层数、步数、普通、精英、领袖、物品、招募。

倍率取实际导入NORMAL/0 scoreFactor=1/bpValue=0；milestoneTokenRatio=1、outerBuffTokenRatio=10、笔记更新窗口/55000最终上限、灵感总上限1900均绑定冻结e915675d数据。蜡烛余数跨探索保留，不能每局单独舍掉不足10的部分。未实现外部增益会拒绝，不能静默忽略。普通钱包/干员/主线进度不随肉鸽失败结算改变。

冻结detailConst明确historicalRecordsMode=NONE、historicalRecordsCount=0，故不伪造客户端历史列表；独立服务端账本仍保留。初始分队及未达条件的收藏/结局、月度任务等不因失败生成解锁。中止/退出、其他难度/主题、外部buff、其他楼层、紧急/Boss和完整主题仍未完成。

REA M151906 LoadData 996/996、exit0、ev_0a49e845ed89cdba5ee7e3555ff41cb7b476c70d504c88602cedd7d91727b0c7，默认读取7组各2个int。M151909 LoadFromResponse 516/516线性解码/exit0、ev_24d166715b59cc8fbd71dce63c6473f95c1885b2bfbd5ee398b34bf41045ee35，默认检查至少7组，但伪代码后半截断，不能称完整方法还原。保留Hotfix/符号警告及混淆偏移边界，原文件/切片只本地。

## 实际检查

首轮15项检查14通过/1重启失败，查明新SETTLED未加入旧地图/战斗状态校验后修正。相关108项106通过/2旧迁移表数断言失败；旧schema夹具移除新表、升级目标更新为71后，19项重点15.24秒全部通过，另1项先通关后失败/回拨检查0.98秒通过，Ruff零诊断。各组有重叠，不累计测试数；1条既有Starlette警告。没有重跑未受影响全套。

覆盖事务回滚、并发和新seq重复、delta、重启/备份恢复、损坏账本/余额/孤立终态启动前拒绝、0022/23/24迁移及失败回滚、已有通关不被失败计作第二次通关、回拨保留结束边界、蜡烛与灵感余数/上限。

新D http-ending-actual复制v17，70→71表：实际HTTP确认200、同/新seq200、delta相等、重新Runtime和备份恢复相等；当前适配策略计算5分/5蜡烛/0灵感（0完成层、1到达节点、0普通通关、2招募）。原v17数据库SHA9659481226e3a508fbdff0c891d9e4858918803c83213edc4f072a8695ccc5cc保持。没有新游玩，官服评分等价未验证。

## 下一步和证据

v18已在新的D目录复制停止v17，旧70表行保持、新schema71表、原输入保护；仅准备，尚未原生验收新确认/评分/返回界面。下一步只观察结束UI，不开战或重复本关/剿灭。无新EXE。完整交付目标保持未完成。

本地证据：.cache/rogue-ending-20261024/{validation.json,actual-http-validation.json,ending-tests-first.txt,related-tests.txt,final-focused-tests.txt,prior-clear-test.txt,rea-score/,rea-detail/}；.cache/rogue-native-20261024-v17/{native-results.json,screen-06.png,requests.jsonl}；v18/prepared.json。DB/官方资源/代码页/截图/日志不提交。

检查点预登记.cache/github-checkpoints/rogue-outcomes-20261024/，待提交与私有远程回读/新D恢复，不预标完成。

## v18原生确认、评分与返回（后续实际结果）

来源90038cf7e0afc48949989bdeb18f1a223acdd5ee、业务a2a9953ab2690d830861aad24e17e8db4ff511d262a24943bbca3cd540ca3eff。仅使用继承的v16脱敏失败，没有新战斗。原生gameSettle第19请求200，7组评分显示：0通过层、1步/1分、0普通战斗、2招募/4分、物品/领袖/精英均0；总分5、蜡烛+5/倍率×1；接着笔记LV0 5/200/灵感+0，确认后主题入口从“继续探索”变为“开始探索”。图09/10/11实际核对，不用HTTP200代替视觉。

25请求全200，只有player_profiles/local_sessions/receipts/rlv2_topics/rlv2_runs/rlv2_game_settlements变化。57其他账号表/58保护输入保持，错误类型计数空。停止辅助句柄60844与原native句柄2349均实际exit0；服务/ADB/index1正常关闭。新Runtime等于最后原生summary，SETTLED/1份结束记录/原1个FINISHED肉鸽战斗保持；没有另跑客户端cold，自动重开/备份恢复与本次原生视觉范围明确区分。

QA失败也保留：首次误用短提交参数触发启动断言，在Runtime/模拟器之前停止，未运行服务；改用实际git rev-parse HEAD再启动。首次status为EMULATOR_STARTING，过早capture为EMULATOR_NOT_READY，未进行点击，待connected再取图。入口本次需START与本地登录点击，不能套用v17自动登录假设。无源码业务重改或重复战斗。

上述原生页面消费证明新适配结构/数值可显示及返回，仍不证明到达/通关口径与官服公式等价。完整主题、其他结果/模式、成熟EXE和整体目标未完成。下一步非战斗节点及楼层流程，通过代表分支后批量扩展匹配接口/数据。
