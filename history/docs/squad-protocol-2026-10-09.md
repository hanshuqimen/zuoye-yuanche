# 编队协议修复与验证

首次真实编队保存请求为 /quest/squadFormation，包含 squadId、slots、changeSkill。
此前它错误复用了本地 Formation 请求；未知 changeSkill 被严格校验拒绝，返回 422。
客户端随后显示“连接状况不良，编队记录丢失”。剧情提交成功不代表编队已经保存。

冻结类型索引确认 SquadFormationRequest.changeSkill 为 bool，而实际请求 JSON 使用 int。
_ParseSquadFormationRequest 普通代码分支遍历当前槽位，比较所选技能与
PlayerCharacter.GetDefaultSkillIndex；任一不同时将 changeSkill 置为 true。
空位写为 null。代码切片位于 .cache/client-metadata/live-squad-request-contract.bin，
SHA-256 为 edb317ace5cd543d358b702d8dc6c64f0d571ab5258109904ab6c8594b4966e5。

修复将游戏接口与本地接口分开，只对 changeSkill 接受 true/false 或整数 0/1。
编队、默认技能、增量和重试收据在同一事务保存；其他布尔编码拒绝。
模组所有权和开放条件尚未实现时明确拒绝，避免无声丢弃 currentEquip。
本地接口的名称参数沿用本地契约；不会被游戏请求当成可忽略字段。

17 项新增检查通过，覆盖空位、首选技能、并发重试、重启、非法技能、外部账号、
未支持模组、响应失败回滚和本地接口兼容。

2026-10-09 05:53:12.541421 UTC，真实客户端战前自动保存编队返回 200（54 ms），
changeSkill=1、squadId=0；四名原有干员及无技能干员的 -1 首选技能已落库。
回执：`.cache/refresh-diagnostic/recruit-oct09-v1/client-validation-squad-first.json`。
早先加入嵯峨的修改曾因旧接口 422 丢失，此次没有宣称该编辑或编辑后的重启显示通过。

## 首章未解锁的独立缺口

第一关 main_00-01 没有前置条件，main_0 的 zoneOpenTime=-1、preposedZoneId=null。
旧快照只有数据库中有 StageProgress 记录的关卡。全新存档没有第一关的 UNLOCKED 状态，
真实客户端进入序章时提示“尚未解锁”。没有手工创建通关记录来绕过该问题。

已按战斗开始使用的同一规则，派生已解锁但未游玩的 MAIN 关卡状态。
状态为 UNLOCKED=0，开始/通关次数为零，读取不创建 StageProgress、战斗或奖励。
已有真实结算产生的开放记录继续保留。组装时预取账号进度，避免逐关重复查询数据库。
主线首页字符串 mainStageProgress 的正确进度选择仍待实现，此改动没有修改该字段。

4 项新增检查通过：首关无写入、不同星级结算的增量、章节与时间条件、隔离及重启。
连同现有检查共 187 项通过（23.76 秒），修改文件 Ruff 通过。
原生普通分支的关卡/区域检查切片已保存。源服务和客户端冷启动后，终端进度显示 0-1；
序章不再提示“尚未解锁”，真实地图可选择 0-1，详情显示未通关及理智费用 6。
此时数据库中 StageProgress 和 BattleSession 记录均为零，未通过伪造通关解锁。
回执：`.cache/refresh-diagnostic/recruit-oct09-v1/client-validation-mainline-view.json`，
截图 74 / 75。随后 `/quest/battleStart` 返回 501，是独立战斗接口缺口，仍未完成战斗闭环。
