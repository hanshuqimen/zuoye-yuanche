# 战斗收藏品奖励：客户端选择链路与后续接线（2026-11-08）

上一轮开战前防护已完成源码43ee121/private0837b79实际回读及新D恢复。本轮继续完整目标中的正常探索，不重打旧关、不恢复剿灭；先核紧急作战和中间Boss额外奖励所需的真实消费者。当前业务1fd3c1ad/192Python/0036-77未变，0新游戏请求/Android/战斗/EXE；本报告为研究进展，不是新奖励系统完成。

## 源码缺口与确定的协议

当前rogue_settlement.compute只产出独立金币/招募券，pending为每组单items/sub0；claim拒绝任何非零sub，且非GOLD分支只会创建招募券。完整回放的claims只接index/at/ticket。因此额外收藏品及多选组须先有版本化保存、选择、库存/资源与回放合同，不能仅把紧急/Boss改成普通kind后放行，也不能只在原生列表加图标。

冻结metadata索引30c555d4/ELF3ece1e7b的直接字段：RoguelikeSelectRewardRequest是int index/sub；RoguelikeReward是index字符串、items列表、done/exDrop/exDropSrc；RoguelikeItemBundle是sub整数、id字符串、count整数。RewardItemViewModel有index和rogueLikeItem列表，SortItemViewStruct另有自己的index和原始bundle。字段偏移只用于核对本冻结版本，不当作通用跨版ABI或枚举值证明。

REA M153308列表领取的默认路径：新请求index取当前奖励模型index，sub固定0。M153331多选领取的默认路径：index同样取当前奖励模型index，sub取传入的点击参数；M153330 OnClick在默认路径检查当前pending类型后将点击参数交给该方法，未据未验证的枚举默认值推断全部类型映射。支持本次需要独立记录并验证(index,sub)的设计，不能继续全局硬编码sub0。

M153636把SortItemViewStruct.index写进子RewardItemViewModel.index；M153638按输入列表顺序建立子模型。M153633 RenderView存在按position渲染卡片/列表的不同路径。原始bundle.sub到全部排序/回调位置的完整映射仍未证实，不能把单个字段或卡片位置直接推广为所有物品类型、非连续sub或Hotfix行为；下次新奖励组采用明确有界输入并须一个新原生选择代表核对，不逐关重打。

M153611默认路径读取主题物品定义、图标及usage，并处理升级/同职业招募显示分支。M153343按明确主题物品定义核对类型。M153637继承父奖励显示状态但调用的M153719默认构造函数静态144字节解码0，不能声称该构造已逆向完成。

## 具体研究与失败

全部官方原始代码页、字段导出、伪代码和原始RPC仅在.cache/rogue-battle-relic-rewards-20261108。

初始v1含M153719，完整性守卫拒绝启动提供器（0/144）；v2仅四个完整方法628/624/236/1164字节，共4代码页/16KB，容器20480字节，56完整函数种子。另一个同页456字节OnClick经过同一完整性检查才加入研究。v3四个Adapter方法920/448/376/212字节，一代码页/4KB，容器8192字节，13完整种子。初始v4两项工厂中M153724只有4/1664字节，守卫再次拒绝；v5只读完整2136字节M153723，一代码页/4KB，6种子。不存在绕过不可解码函数或读取堆/认证。

M153723的REA观察ev_d0d34527c41f47c2d3638646aa1a3474febfa945c0afc6f0e12993ad8035bb66在静态间接跳转表处保留无法模拟/间接调用警告；完整线性解码不能代替全分支语义。为补具体上下文，v6先错误地只允许PF_R=4源段而StopIteration；实物ELF该静态表在可读PF_R|PF_X=5段，v7按文件可读位核对后，精确复制0x94d9d80..0x94d9dde的94字节，只给分析容器增加只读数据段。原4096代码字节逐字节同、0callee字节、0RET或返回值补丁。v7容器SHAf52e0379ee83b0747362f6178cb1e882d6c8537f2154b0785dac85b20e23abbb；实际REA请求返回provider_timeout，无新伪代码，不能称跳转表问题已修复或全部case已恢复。未重排请求；停止该会话并保存失败。

独立静态ARM64调用点记录factory-static-call-sites-v1.json只核同一2136字节工厂的直接callee/参数身份，保留范围限制；不能冒称REA已恢复未得到的case。未以“保护导致截断”笼统归因，也未为这项研究修改产品/客户端。

10个成功方法观察的证据ID、正文摘要/警告、调用metadata绑定在verification.json.findings及各findings文件：M153308、153331、153343、153611、153330；M153633、153638、153636、153637；M153723。默认路径和Hotfix警告分别保留。两个45秒观察先到期，随后原请求58.485/51.282秒成功，未重复排队；v7真正provider_timeout是已返回错误，和观察到期不同。

四个REA包装执行45314、11464、19664、20078均实际exit0，server_exit0。v3 close_binary另报cleanup_incomplete（观察java短名与期望绝对路径不符），该失败不被包装exit0抹掉；工具报告Linux485，随后两次聚焦ps都exit1/无进程。其余三会话close成功，八个Windows包装/子PID现场均不存在。保留失败分析目录和/tmp socket边界，不称所有系统写入都在D盘，未停止其他程序或模拟器。

## 当前数据与保存保护

实际19表e915675d/v077/77.6.0/client_verified=false，对冻结CN2.7.71/V070，不称全表同版。限定rogue_1/NORMAL0，固定时点1793102400已开始且归档；90个关卡目录/10区域、36普通/36紧急/9Boss区域绑定的上一能力矩阵仍是上下文能力，不是自然资格。首主题实际详情本次按候选drop键路径遍历，仅命中trapRewardRelicId的null；不据此断言所有资源或后台都无概率配置。235 relicParams、265 relics、342 items及空rollNodeData都不能直接变成官方掉落池。

只读参考[PRTS主题页](https://prts.wiki/w/傀影与猩红孤钻)发现页面混有回顾更新、旧主题记录；未取得本冻结NORMAL0的完整战斗藏品候选/权重直接证据，未将搜索命中或商品出售资格推广为战斗掉落资格。

audit_v1初次把旧native准备记录中的heartbeat-latest哈希当成永久不变，实际断言失败/exit1；唯一不符项是上轮已经验证的新检查点索引。旧原索引在playable-admission-20261108/previous-heartbeat-latest.json中逐字节保留，新索引逐字节等于该阶段upload-verification且source43ee121/readback_verified=true。保留失败，不回写旧期望；audit_v2只承认这一个有独立证明的授权索引更新，其余资源/保存检查未放宽。

audit_v2实际exit0：257受核输入保持、192业务文件摘要全同；原生DB与本阶段第一次scope读取的字节hash同，77原始表与上轮已验证27完整用户副本全部相等。没有新Runtime写入/迁移/奖励/存档改动；复用上一完整恢复证明，不为文字重跑119检查或备份恢复。证据verification.json、actual-table-scope-v1.json、metadata-contract-v2.json、audit-v1-failure.json；并非本阶段重新完成原生或27用户备份恢复。

## 下一项实际开发

接持久化、版本化的战斗收藏品奖励方案：开战前冻结可信服务端给定的候选/来源与规则摘要，领奖按组和sub验证，只发所选项，拒绝重复冲突或客户端自报物品；复用已有收藏品库存、费用屏障与因果重放，再纳入图鉴、结束记录和计数。旧金币/券及已保存策略/收据保持原样。先明确方案资格与数据来源，不从普通商店目录反推战斗概率；未知后台概率单列，不能靠默认全池/空成功伪装。

该依赖接齐后再启用中间Boss/紧急完整结果和正常地图供给，并只做必要的新原生奖励选择代表。下次直接复用本批已完成消费者证据，不重开同样10方法或为记录重打旧关。本轮仅研究/文档，已有私有0837b79覆盖当前业务，不为纯研究文字重复bundle。完整Prompt/全部命名模式/原生视觉及体感、Golden/断网长时/性能/Harmony/成熟EXE仍ACTIVE未完成。
