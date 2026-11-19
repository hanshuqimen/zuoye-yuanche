# 商店访问后的探索结束与楼层合同（2026-10-25）

上一目标回合属于进展：商店交易源码、一次代表原生及私有回读恢复均有实物证据。本轮当前HEAD以Git为准，完整交付目标继续active；不重打任何关卡、不恢复剿灭，不因局部HTTP通过声称全主题可用。

## 商店结束统计修复

722a616在已访问商店后会主动返回ROGUE_SHOP_ENDING_UNSUPPORTED/501。本轮用保存的该提交实代码在自有QA账本上重现只读拒绝，同一状态由当前空gameSettle请求成功，未用万能成功绕过数据守卫。

新增rogue1-normal0-prts-score-shops-v3版本化结算事实：场景、商店、已有普通战斗共用先前的节点/资源事务重放，计入已完成商店的一次到达；未来PREPARED报价不计入。购买招募券不等于招募干员，源石锭和券不计物品分。只有保存的实际招募记录计招募分；结束摘要绑定商店rule_hash、进入前资源、券ordinal、购买与进入/离开时间。保留V1、V2原事实及hash，不改旧收据/账本，不新增迁移，仍schema0027/73表。未完成楼层、多难度/主题、精英/Boss及外部buff仍按原边界拒绝。

依据仍是[PRTS傀影主题的古堡笔记评分说明](https://prts.wiki/w/傀影与猩红孤钻#古堡笔记)，属于社区规则适配，不能冒称逆向出的官服计分代码或官服等价已证实。实际冻结CN2.7.71/build190及e915675d版本继续绑定NORMAL/0倍率/笔记窗口/灵感上限；主题已完结仍可游玩，未将首页展示截止当不可用。PRTS页面抓取/行号和find先出现错误/超时，未据此判没有规则；改公开MediaWiki API取得原始wikitext，明确物品统计排除币和券，原文只本地保存，不进Git。

首轮10项8通过2失败，查明测试在新seq收据/修订写入前取了备份比较快照；改测试快照时点后关联42项42.76秒通过，Ruff/diff检查通过，一条既有Starlette警告保留。覆盖shop→普通失败及scene→shop→失败、自有加密HTTP夹具、消费/券不重复计物品/招募分、差量/新seq/并发只发一次、恢复、损坏商店/报价/政策只读拒绝、事务失败回滚；没有增加实际战斗或额外原生验收。另执行722a616实代码生成V1/V2结算账本，新Runtime重开73表全行与完整同步相等；3项4.26秒通过，和42关联分列。

实际停止v18结束存档在新D目录71→73，仅两空表和版本号；既有行/旧hash保持，完整rlv2等于当时原生末快照；原SHA aa816d72ab923447711d7f706a15b783abbd010a441026606ddebdd6206cb03a、60保护输入保持。实际v23商店存档在新D重开73表全行保持、完整rlv2等于末次原生，原SHA23544ff878d1f53704ff602d553643b3c8f5a81014e374df60dcf82992e5f073、74输入保持。冻结数据V3计分示例为QA纯计算6分，不是冻结数据V3真实战斗/原生通过。首个辅助误读不存在的Settings.fixed_time而退出，新v2目录改用实际Context时钟后通过；失败副本保留，原存档未改。

业务9b53aa47af0ee799dc17c1d3485aec4f10552c954285d1d71be4181e424e164e；本地.cache/rogue-shop-ending-20261025/{tests-first.txt,related-tests.txt,prior-counterexample.json,prior-compatibility-tests.txt,existing-save-validation.json,prts-source.txt}。V3原生结束未重跑；既有7组评分wire显示已经验过，本轮只扩展保存事实/同类计数，不能扩大为本次原生通过。无新EXE，完整目标未完成。

## 楼层合同研究

冻结现代metadata中MoveToRequest含to位置；FinishNodeRequest无本类字段，不能从类名猜实际路由或确认它负责换层。ZoneRewardRequest有itemType，SpecialZoneLeaveRequest无本类字段。实际表rollNodeData为空，没有从空表获得官方生成权重；区域目录与关卡资格仍用已冻结守卫，未知列/池/概率保留缺口。

仅读冻结磁盘ELF代码，无启动模拟器/堆/凭据。REA三句柄2295/71009/45664均真实exit0/stderr0：M153848 NeedZoneTransition184字节、M151106 OnSendConfirmRequestImpl696字节、M151043 CreateTransitionParam292字节完整线性解码。证据ev_e84eb0be1d6d5baaf4834d37802e9c82899693620c79e55588b87e07799f8521、ev_d3d771e5c1f8f9e9371ce0e5e4ae1cad17010571661c5e40a6beb4d5b82131f2、ev_b83025045877925c51a4f9e27ebdf82581d1196c3e43feed4f1943e929fc82b7。默认确认函数构造M28320 MoveToRequest、从焦点节点构造位置；未证明换层API。过渡检查读取两个bool位置，Hotfix坏指令截断/全局符号警告保留，完整线性解码不等于完整动态控制流。

ZoneViewModel/TransOptions部分metadata偏移为约1.68e9的非正常对象偏移，因此不能把字段名硬套到native+0x21/+0x22；未据此改产品字段。M151599 LoadData696字节在磁盘0解码，守卫没有启动其REA，不能擅称缺口原因。下一步用新的第二层QA同步投影只观察换层显示并读取所需已加载可执行页，保持产品存档原状，不进入旧关/商店或战斗；观察不是产品换层成功。本地.cache/rogue-floor-20261025/{model-contracts.json,view-model-methods.json,findings.json,rea-static/,rea-model/}。

## v24第二层QA观察和加载后的模型

2026-10-25楼层v24观察：005c039/业务9b53aa47，独立73表副本只投影cursor.zone2/map.zones2，原生落阳庭院过渡/背景/单节点可见；50请求全200/rlv2请求0、没有进入节点或战斗。原句柄80550 exit0、正常关闭所属服务/ADB/index1；只local_sessions变化，59其他账号表/76输入保持，新D73表重开原始同步仍zone1。读取唯一已加载可执行页后M151599 696/696字节/REA句柄44072真实exit0，默认用旧/新DungeonZone.zoneIndex比较设置过渡标志，实际offset24由有效Zone类型及调用关联确认，不用大偏移硬套。此为客户端合同/QA呈现，不是产品换层成功；下一步独立多层游标与按zone区分节点/战斗身份，保留旧单层账本/旧客户端表现，不能凭此启用未知正式随机池。全目标active。

LoadData从RoguelikeDataUtil取得当前DungeonZone、Depth和Index，比较旧/新zoneIndex（有效DungeonZone字段offset24）；模型先前无zone且未accessedInitState时写一个过渡位，否则写另一个。结合本次手动时钟页与默认NeedZoneTransition/CreateTransitionParam可区分初次手动与后续过渡路径，Hotfix/全局符号及数字状态枚举边界仍保留，不声称全部动态行为还原。evidence ev_401fac608e4dcbf1b536ab74ce1f214be6c821b0630dd0c013cc6f869b1df56b，方法体SHA fa2a388abccd6d91f515c6cecc1ae05e984efc70a1e93be5a09038d9daa7a171。

本地.cache/rogue-native-20261025-v24/{prepared.json,requests.jsonl,native-results.json,summary-0014.json,errors-0015.json,screen-04..06.png,loaded-code-receipt.json}及.cache/rogue-floor-20261025/{native-projection-validation.json,findings.json,rea-loaded/}。原始ZoneViewModel大偏移并没有被修正到全索引，只有这些明确默认路径取得代码依据。没有新成功路由、发行物或产品楼层推进。

## 私有检查点回读恢复

2026-10-25检查点7e11c5d真实完成：私有连接器上传420d2cde、README索引f9c68a48；精确提交网页raw回读SHA a920343d及新D388文件/99提交/fsck/Prompt相等，句柄94200 exit0。原150根项及索引原正文/151非README项保持。初次辅助编码utf8-sig无效与浏览器重置后旧绑定失效均保留，分别修正编码/重新绑定已有授权tab后成功；未改权限/公开性/凭据、未动模拟器或存档。该包含业务9b53aa47，后来的多层源码3ebf64a4尚不在其中。实际索引.cache/github-checkpoints/rogue-shop-ending-20261025/{upload-verification.json,checkpoint-web-proof.json,restored-remote-7e11c5d}和heartbeat-latest。
