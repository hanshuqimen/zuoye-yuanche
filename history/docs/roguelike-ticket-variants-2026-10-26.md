# 普通多职业招募券批量适配

当前：31新+130相关共161不同检查、冻结16普通类/20特殊拒绝及新D74表/旧原生保存恢复通过；业务31f0466a/schema0030。0新原生操作/战斗/EXE。下文“正在修改/请求等待”为阶段原文，最终事实见末尾；c2580d5私有完整包已回读并在新D恢复，完成记录另存。

## 当前范围

遵照用户效率安排，不恢复剿灭、不重复旧关或已过的免费/付费晋升原生代表。本阶段沿用同类接口，扩展规则明确的普通招募券；原生逐券游玩不是本阶段计划。完整主题、正式随机供给、费用修正、特殊临时招募和成熟EXE仍未完成。

基线HEAD为7ed700d，业务指纹1221eaec/schema0030/74表。此前232不同检查、冻结20HTTP及v32原生是旧基线事实，不能作为本次新增源码已通过的证据。最近私有完整包81e72ce及实际回读/新D恢复保持。

## 冻结数据与合同

匹配CN2.7.71、19表e915675d。实际36类recruitTickets：初始8职业普通券、8类无特殊效果多职业普通券及20类特殊券。新增范围为all、5star、double_1至4、quad_melee、quad_ranged；同时核对原始profession/rarity掩码、展开列表、extraEliteNum=0、extraFreeRarity为空、物品类型与THIRD_LOW备用引用。

备用列表是明确表引用，不能再按职业过滤：例如双职业2的备用包含CASTER，虽然其普通干员筛选是TANK/SUPPORT。五星以下同时限制普通新招募和有成本晋升，不能只限制展示。

反例保留：all_discount的用途描述为部分干员直接进阶，不能按英文后缀当普通折扣；all_premium保证精英临时招募，不能把extraEliteNum解释成直接晋升人数。red/sp、带discount近远程券等20特殊类本阶段不接纳。单一rollNodeData为空不能推广为没有正式供给规则。

本地来源（不提交官方数据/代码页）：`.cache/rogue-economy-20261026/cost-source-inventory.json`、`variant-contracts.json`、`recruit-ticket-native-fields.json`。FrozenNativeTypes已核对type4980的profession为ProfessionCategory、rarity为RarityRankMask及展开列表/特殊效果字段；元数据索引30c555d4、ELF3ece1e7b、metadata bf14421b。静态类型不等于服务端概率/热更新合同。

## 实现决策与验证状态

新catalog包含已接纳普通券，旧tickets仍保留初始8职业池，用于旧配方和确定性战斗奖励。扩展目录不改变旧奖励哈希/掉落，不自动启用任何正式节点随机池。普通候选、付费晋升、保存校验、商店明确报价及旧无声备用响应适配共用完整目录。现有晋升历史policy/hash与schema不变。

源码正在修改，新增检查、冻结旧存档/新D恢复及提交尚未完成。REA会话已从实际PID/ready恢复，没有因输出截断重启；M33666静态反编译请求仍在原会话中等待。未取得的结果不作为依据。


2026-10-26普通多职业招募券完成本阶段批量接线：8新增类/all、5star、double1-4、quad_melee/ranged，合计16普通类；普通候选/付费晋升/资格保存校验/明确商店报价/旧无声备用适配共享目录，旧8券战斗奖励池及历史哈希保留。当前业务31f0466a/schema0030/74表。31新+130相关共161不同检查通过（guards-v3 15、transactions-v2 8、related-v1只取8个已过paid用例、regressions130），Ruff通过；Starlette既有弃用警告保留。冻结e915675d全部16普通报价可编译/20特殊拒绝；新D目录Runtime重开、备份恢复74表/旧v32账号4及v30账号3完整rlv2相等，原数据库字节SHA和80保护输入保持。0新原生操作/战斗/EXE。REA原会话29004在首次M33666 provider_timeout后状态核对、同会话重试成功，M33666/M33667/M33709共3静态消费者取得；M33709普通计数同时按职业位与稀有度位筛选，不能据此推断特殊费用/临时招募概率。Hotfix、全局重叠及类型传播警告保留。公开close完成/manager completion exit0，现场wrapper/child缺席，代码页SHA保持。失败保留：variants-v1的4项为QA缺gameConst及误把isUpgrade且typeNORMAL当新招募；variants-v2修正后30过；related-v1新增正常招募8项初始希望耗尽，保留ROGUE_HOPE_REQUIRED后改为正常REST+3前置，未削弱业务限制。该次-k连带筛掉其他文件，随后单独运行130回归。Ruff初次导入空行已修正。当前31个新用例最终分别验证；没有为补记录重跑已过场景。费用修正/正式随机节点供给/特殊20券/完整主题/其他系统/成熟发行仍未完成。详细报告docs/roguelike-ticket-variants-2026-10-26.md及.cache/rogue-economy-20261026/variants-validation.json；当前新增修改尚未完成新的远程回读，旧81e72ce检查点保持。


2026-10-26普通多职业券检查点c2580d5已完成私有远程回读/新D恢复：412自有文件/119源码提交/414历史路径/1492blob扫描，禁止路径/凭据标记0；完整包1558707字节，SHA256 0beeef2f539ec43377a6cfc6da881198ff5cb74c30ba785f25985aaa02efa54c，Gitblob3506e6aff7dc06800b6c54e952df1b82885cb8ee。上传/索引d1e3f033以旧a44dd54b为父，162旧非README根项及旧索引全文保持，根项164，实际private。Git CLI无现有凭据（关闭交互）/codex-development APIref404，因此使用已授权完整bundle备用路径，没有声称源码分支正常push。精确提交GitHub网页实际下载字节与两种SHA一致，新D恢复412源Gitblob/完整119历史/Prompt/fsck/干净工作区相等。浏览器默认下载短暂落C，仅将本次新下载且再次验证SHA的文件移动到D received-web/browser-original-c2580d5.bundle；旧包/下载/保存/发行物保留，无权限设置/凭据读取。网页第一截图显示c258标题/源提交/业务哈希/字节，第二显示完整SHA及16类/161检查范围；两图互补，不用单张裁切图声称全部可见。证据.cache/github-checkpoints/rogue-ticket-variants-20261026/{upload-verification.json,checkpoint-web-proof.json,restored-remote-c2580d5}，权威heartbeat-latest/local-latest已指向c258。包内含业务31f0466a/schema30/161不同检查/冻结新D74表与80保护输入保持、REA首次超时及原会话重试/3默认消费者；0新原生/战斗/EXE。特殊券/费用修正/正式供给/完整主题和成熟交付未完成。当前远程完成记录在后续本地提交，不在c258源包内，不因此重复生成纯记录包。
