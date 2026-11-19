# 首次通关、任务领取与展示状态验收

本轮使用独立存档 native-mission-fix-oct10-v1、测试实例 1、冻结国服 2.7.71。
正式存档和旧 Windows 程序尚未更新。游戏外网限制保持启用。

## 首次真实三星结算

在保留的通关前备份上重新游玩 0-1，battleId 为
e615bc3b-0fb7-449d-8806-997a48523e19。
02:33:46 UTC 的第一次 battleFinish 返回 200（117.7 ms）；没有结算重试，
客户端进入结尾剧情并显示三星结果，返回地图可见已通过的 0-1 和已解锁的 TR-1。

理智 123→117，玩家经验增加 72，龙门币增加 72，首次奖励源石和招募许可各 1，
基础作战记录增加 4。该次只推进 MAIN.main_1 和 GUIDE.guide_4，
没有旧实现中错误推进的其他关卡任务。重启服务器和客户端后，已通关进度与上述数量保留。

这一结果验证了非空任务增量的首次解析，不能据此声称全部战斗流程通过。
当时 saveBattleReplay 仍返回 501，结算画面出现战斗记录保存失败提示。
结果画面的两个经验样式图标仍待核对；实际玩家经验只增加一次。
固定时钟下，长时间停留时客户端会自行推算理智恢复，重新登录后重新显示存档值 117。
实时钟下的长期显示一致性尚未验证。

证据在该诊断目录：native-first-finish-validation.json、
native-first-finish-0008.sqlite3、native-finish-public-response.json，以及 021–028 截图。
旧错误存档和重试成功记录继续保留，未替换为本次成功结果。

## 实际领取与事务边界

客户端主线任务页正确显示“通关主线 0-1”完成，但点击补给时访问此前缺失的
/mission/confirmMission，返回 501 并显示重新登录提示。
冻结 ConfirmMissionRequest 只有 missionId；ConfirmMissionResponse 继承
PlayerDeltaResponse，没有额外声明的奖励字段。

现已实现单项永久计数任务领取。任务、所属组、前置、目标和奖励读取匹配的 GameData；
奖励授予、claimed、下一项主线任务和响应收据在同一事务内提交。
重复序号、不同序号重试以及新会话重试均不重复发奖。
非完成、其他账号、未知任务、物品上限和响应组装失败不会留下部分领取状态。

03:16:38 UTC 的真实请求 missionId=main_1 返回 200（50.47 ms）。
客户端显示基础作战记录 ×5，仓库 2001 数量 4→9，main_1 保存为 claimed，
main_2 保存为进度 0，GUIDE.guide_4 保持原进度且未领取。
任务教程通过正常 story/finishStory 保存，未手工改教程标志。

证据包括 045–054 截图、native-claim-before.json、
native-claim-first-public-response.json 和 native-first-claim-0008.sqlite3。
备份 SHA256 为 633ad902c980e8544112f6cf5b7950468f38fb4680c29167472c68e448f0a867。
再次重启服务器和客户端后，仓库仍为 9，main_1 保持已领取、main_2 保持进度 0；
理智仍为 117，玩家经验仍为 72，已完成的任务领取教程没有重播。
冷启动检查和当前源码指纹在 native-claim-validation.json。

## 进行中任务状态的第二处修正

第一次领取后，main_2 虽已保存却未显示。第一份真实领取响应保留了当时的 state=1，
没有覆盖证据。进一步读取冻结客户端的有界、文件映射 ARM64 代码发现：

- MissionModel._DealWithMissionData 的 MAIN 分支只展示 holding state=2 的任务。
- MissionViewModel.CheckIfAbleToFinish 分别检查 state==2 和 value>=target。
- 因此已分配而未达标的任务也需要 state=2；可领取性由进度决定。

同步组装已修正为未领取的已分配任务 state=2，已领取任务 state=3。
未达标任务的领取请求仍明确失败，不把状态 2 当作完成或发奖依据。
无独立组奖励的 MAIN 组按成员领取派生 0/1；GUIDE 的独立组奖励不会由此标记已领取。
源码检查通过，领取后冷启动已验证。修正后的下一项任务显示仍未验收：客户端进入了
下一段训练引导，尚未再次打开任务页。不能用存档里正确的状态替代画面验收。

代码指纹及方法地址补充在 data/research/client-native-mission-contract.json；
有界切片回执在 .cache/client-metadata/live-mission-model-oct10.json 和
live-mission-finish-check-oct10.json。没有读取认证数据或玩家对象内存。

## 该阶段的回放与支持边界

以下保留训练适配前的失败记录。后续 TR-1 固定阵容、二星/三星奖励、main_2 领取、
main_3 显示及服务器/客户端冷启动已通过，详见 [训练与恢复验收](training-battle-2026-10-10.md)。

冻结 AutoBattleConvertUtil 和 ZipUtils 代码表明原生回放是 Base64 包装的 ZIP JSON。
新增 saveBattleReplay 的有界解码、归属、完成状态、三星、关卡、数据版本和记录顺序检查；
相同记录重试不修改奖励，冲突或迟到记录不覆盖新记录。
读取和代理开始仍未实现，实际客户端 ZIP 请求尚未捕获验证。
只有匹配的新原生记录才展示 hasBattleReplay，旧本地任意字典不再冒充可用代理。

单项领取当前只覆盖已核对模板的永久 MAIN/SUB/GUIDE 任务。
周期积分、限时规则、独立任务组奖励、其他模板、新账号完整任务分配和全部支线解锁未完成。
遇到尚未适配的后继主线规则时事务回滚并明确报错，不能声称主线任务链全部可用。
TR-1 训练关卡和其后的完整游玩仍待实现、验收。实际训练编队页显示固定的巡林者、
芙蓉、夜刀；03:33:12 UTC 的 battleStart 请求 squad 为 null，被普通编队请求结构拒绝，
返回 422，客户端显示重新登录提示。理智、经验、奖励和 TR-1 进度没有改变，也未创建战斗。
071 截图及 native-claim-validation.json 保留该后续失败；训练引导尚未提交完成。
训练适配还须正确处理固定阵容、无理智消耗以及首次干员和源石奖励，不能只把空编队改为成功响应。

回放新增 14 项、领取新增 15 项检查；修正状态后完整 288 项通过（53.88 秒），Ruff 通过。
这不替代真实代理、完整任务、所有模式、断网冷启动或连续两小时游玩验收。
