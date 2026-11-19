# 肉鸽结算记录与冻结关卡依据（2026-10-23）

完整交付目标保持。继adc1c87实际开战请求纠正之后，本轮继续结算及节点推进的前置，不恢复v35剿灭、不重复游玩关卡。**没有启动Android/模拟器，没有捕获真实肉鸽结算，没有开通虚假的成功结算路由。**源码仍schema0023/69表，无新EXE。

## 源码实际范围

新增严格RogueFinishRequest，继承data/battleData并要求battleLog、rlv2Data.battleSnapshot。battleLog显式null与缺字段区分；null只表示没有记录，不允许据此发奖。快照按有界Base64/单ZIP/UTF8/JSON解码，预算100万wire字符、4MiB展开、2万行、10万累计死亡（本地接纳预算，不是官方所有模式上限）。只接纳actionKill字段和四整数行，拒绝未知/重复JSON键、隐式类型转换、非法ZIP/CRC/压缩类型、多成员、前后附加内容和超预算。仅内存读取，不提取ZIP路径。保存原始wire摘要与动作顺序；不根据一个例子推导所有坐标非负或三坐标唯一。

普通/剿灭解码器原有的中断rank限制保持；新增肉鸽纯解析保留rank和interrupt/giveUp事实，**不把rank当普通星级或直接认定胜负**。模式结算必须另有业务准入，解析通过本身不提交任何结算。

独立inspect_finish先校验游戏会话及账号拥有的RogueBattle，再核对Run/地图/版本/原会话/不可变编队，最后解码、绑定战斗ID/关卡及journal。journal中的干员集合、技能ID/下标、模组/模板/助战必须匹配已保存局内快照。只读检查，无HP/经验/金币/奖励/节点/收据写入。尚未把journal随机种子当肉鸽meta.seed、也未把快照死亡数当validKillCnt；两者需分别证明。没有新增battleFinish成功HTTP接口。

92项编解码、普通/剿灭相关检查通过10.65秒，随后8项拥有权/局内编队与无写入检查通过7.88秒，Ruff零诊断，各次有1既有Starlette警告。是自动检查，不是原生结算成功。首轮Ruff仅移除1个无用import，无测试失败。本轮没有重复无影响的全量检查/关卡。

## REA与声明依据

冻结metadata索引30c555d4、原ELF3ece1e7b。全部提供器结果均实际等待终态exit0，不把文件存在或观察超时当完成。原生反例/旧磁盘保护失败都保留。仅解析本地代码/资源，无堆、认证、日志或官方账号访问。

- M84584 FetchGameOverBattleSnapshot，0x2bbc8dc、1312字节，ev_44cfbe0d227ca7efba880e4e15668f1cc148376791acad5a1d7b1cb9ca036e33：输出actionKill的四整数行，再调用具体RoguelikeBattleSnapshot实例的CompressToBase64。
- M77331具体实例0x61b5944、1136字节，ev_4adc0dfd72030c08a3cc89e6822e6bd18d81697ec7caef7d570e4aa23d6ae820：默认路径JsonConvert.SerializeObject→Encoding.UTF8→ZipUtils.Compress→FormatUtil.BinaryToBase64。泛型参数19779是RoguelikeBattleSnapshot，不是裸List；不能误按无对象包装的数组解析。异常展开跨邻接函数有控制流截断警告，只使用已映射默认路径/调用地址。
- M219791 ZipUtils.Compress，0x9028bf4、1532字节，ev_a74d3e88a9b903fef1aa516ddc680ef7bb3e86e66ef99356ec964db27dcbfbf3：单ZIP输出流与entry，默认路径可读；Hotfix间接跳转/异常展开有警告，不声称所有分支还原。
- M84585 RecordFinishedEnemy，336字节，ev_095caf9c14fecc310e84bf4f2805b623e49b6fb3c5061295e46437b329c3d22b：调用Entity.IfReasonIsDeath再按ActionID累加，不是所有完成/漏怪计数；Hotfix路径截断。原ActionID含subSchedulerI/waveI/fragI/actionI，不能贸然把投影坐标去重。
- M77336公共ComposeBattleRoundFinishData，1424字节，ev_892df3c7217538d8ac29101862cffd1ae70d7d31b785bafaa68a36a124997d0b：公共封包组装，Hotfix分支截断；不据此猜肉鸽胜败或奖励。
- M33658，264字节，ev_5ced4d69120019a3af85cced52bfd7404203bdf4a83bcd7cba9725bf5937ed24：默认路径检查首BATTLE内容state==0，Hotfix控制流有截断。为当前state0候选增加静态依据，仍没有成功原生开战消费证明。
- M153867 BattleFinishRedirection，596字节，ev_2d04c1a6eb308419641975e4eb219847e03c7128d893276a16b3702cdbf841f2：结算后按pending场景返回；不是完整奖励UI证明。
- M84602 TryGetRoguelikeEnemyExpPattern，668字节，ev_adfc5dc0b724e69cd8cf82a9661d18c59f06684a88ee907af89db0de6fdb9cc0：按当前主题gameConst(+0x120)的exploreExpOnKill(+0x288)读取三项模式串。冻结19表中rogue_1/2为null、rogue_3/4/5/6为10,20,100。该分支不能应用到傀影，撤回“为首主题引入按敌人类型的经验数组”的研究方向。
- M84535，240字节，ev_63a9b1d37ea862a990cce6e6a6fc607de45b4e79d7e898fdbf7fa420433cfef2：初始化且有效击杀时才按enemyLevelType取上述数组，Hotfix分支截断。

M33775 GetLevelWithExp磁盘仅4/204字节解码，没有启动提供器；升级的累计/逐级计算仍需取得确定依据，不能只凭表中10/24/36等数值猜算法。上述9次REA结果的摘要、警告、evidence_id在.cache/rogue-settlement-20261023/validation.json；完整原始输出仅本地。

## 批量关卡资源核对

先扫描已缓存的5个公开热更新包，0/54目标，不把缺失变为空数据。随后从已冻结原APK（SHA256 0b79b853...）扫描94个anon候选，第二包assets/AB/Android/anon/343effe24b5c2515941a75309192d128.bin即找到全部54份level_rogue1资源，覆盖当前e915675d的90条关卡引用。逐项核对RSA/PKCS1v1.5/MD5资产签名和原始SHA256；V077/26-09-22-07-47-20_6c71fa清单没有覆盖这个包，因此实际来源为基包。不是把签名有效等同于任意更新版本有效，没有额外网络下载或修改APK。

按已匹配声明显式投影54资源的options、runes及waves/fragments/actions字段，批量取得63波、2046动作、596隐藏分组动作。只是有界投影，不是完整FBS/关卡解码，不解析所有branches/敌人覆盖/运行时动态行为。普通/紧急可能共用一份level文件并由难度rune区分，不合并玩法规则；隐藏/随机/额外敌人不得全部计入必出敌人。示例意外level_rogue1_1-4 SHA256 da4a419b1ecf4abb89885202ece2522304b5e5718ce82a5cbaaf3a015dac6d39，与ro1_n_1_4及ro1_e_1_4分别绑定。额外金币陷阱、稀有敌人也需后续按具体节点/增益核对。

本地signed-apk-level-index.json、all-level-projections.json、projection-summary.json记录全部引用、摘要和未解码范围；原始关卡和聚合投影均是官方资源，留在.cache，不进入Git，也未导入替换现有服务器数据。

## 公开资料与当前缺口

只读研究[TerraPS固定提交1731c82](https://github.com/DoctorateRS/TerraPS/blob/1731c82dc4d853d6a80134070a319ad4e48b8a30/crates/terraps/src/game/rlv2.rs)：其示例固定宝箱/陷阱数、简化奖励，并存在清空pending的逻辑，不能作为官方结算规则；未执行或复制进业务代码。首次搜索返回无关项目，未采信。

[PRTS傀影区域资料](https://prts.wiki/w/傀影与猩红孤钻#区域)列出区域、作战类别及特殊事件分别对应的基础奖励，并区分增益后的显示数值。社区资料可作下一步显式规则来源，但仍须绑定具体关卡/模式/实际导入版本/开放与增益条件，不把它标为官方协议fixture或完整原生验证。

下一步：核实首主题分层/特殊作战基础奖励与升级算法，接入原生胜败/生命损失、奖励pending/领取/招募及节点完成；然后在必要的首个代表战斗中验证完整开战结算，不重复旧关。全主题/正式地图供给及概率/其他主题和用户指定全部模式、成熟发行/Golden/断网/两小时/性能/HarmonyOS仍未完成。


## v13加载升级方法与当前新增曲线

上文“M33775磁盘4/204、升级算法未定”保留为研究历史。v13由正常停止的v12在新D目录复制69表完全相等，无新夹具。只读文件映射0x44ff000代码页4096字节（SHA256 793e7719736683e6e236852615b36e77d8019459eb1553cc5349923c58da4342），硬件/index1/APK/ELF/映射与8秒Android命令守卫均保持。没有读取堆、认证、官方账户或日志。

启动曾返回EMULATOR_STARTING/TIMEOUT，继续观察原执行句柄，未重启，随后同一会话connected。没有点击UI；客户端自动恢复本地登录，因此撤回准备脚本“no game login”假设。实际12请求全200、无rlv2，仅local_sessions变化、无普通/肉鸽战斗，57其他账号表与41输入保持；正常清理并观察原exec句柄exit0。第一次按“PID不存在”检查失败，查明旧40752已被不匹配任务的conhost.exe复用；再按Python名称/命令身份确认原来源退出、18443关闭，未对复用进程做任何操作。index1/所属ADB已关闭。不为补记录重做已通过且未受影响的Runtime/备份恢复。

加载后的M33775，204/204字节、10个完整方法seed，方法体SHA256 62fca6b61ce79574555414c1335181691784bb421acd9f690b4d11048e2c79d6；REA退出0、ev_0699310b058d8123aeb548a2ea2d394efe369eb3a31c17e22ce33f6a39dc480b。仅全局变量重叠警告，默认循环完整：从level2开始取下一等级行，累计经验减去其exp，仍非负才再尝试下一行；不足或下一行不存在时返回当前等级。PlayerLevelData.exp确在+0x10，与汇编相符。没有逆向Hotfix替换实现或证明全部升级UI消费。

新增FirstThemeLevelCurve及GameData.rogue_levels惰性入口：等级表连续、有界，五个成本/增量字段明确，拒绝缺失/未知/非整数/负数/累计溢出；冻结成本与希望上限、携带上限、部署上限、最大生命四种独立增量。累计经验定位提供当前级内经验/下一级成本，满级保留剩余经验，不推导满级奖励；gains只统计新跨越的等级，不重复或倒扣。这里没有改变Run、HP、奖励或成功结算接口；实际结算尚需接入。

27项检查0.09秒/Ruff零/1既有警告。冻结19表e915675d所有边界核对通过：10经验2级，24仍2级，34为3级；满10级累计455经验，升级希望上限共+54、可携带上限+3、部署上限和maxHP增量均0。不是把剩余经验改为累计门槛或把携带增量当部署增量。无原生升级游玩、无新EXE。当前业务f5564b95050bdf9b14661c9d077ea9e81cbe22577e365b5aa6a53eefb94ca0c5，schema0023/69表保持；之前92编解码与8拥有权组未受独立曲线影响，不重复执行。证据level-curve-validation.json及levels-tests.txt。

下一步将分层/特殊事件基础奖励与该曲线、胜败/生命损失、奖励pending/领取及节点完成接入同一事务，再做必要首个代表原生战斗；不重复已验证关卡。全目标保持未完成。
