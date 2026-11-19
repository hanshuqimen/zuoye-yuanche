# 指挥经验栏消费审计（2026-11-09，进行中）

当前（2026-11-10）：已修复协议投影，并以保留第四层地图实际观察LV2 22/24；源码2ffbd1d/业务abce9908，281相关检查及完整28用户78表恢复通过。新私有回读尚待完成。以下保留研究时的未修复反例和失败，不将地图代表推广为全部奖励动画/满级/Hotfix均已原生验证。

原生QA28领取代表的019结果、021列表、023三卡、029第四层地图持续显示LV2及32/24。已经归档为真实未修复缺陷；领奖功能及恢复通过不等于视觉完整。沿用已结束保存和静态代码，不重开/重打任何关卡。

当前业务bed2afda/194Python/0037-78，源85b425f/private2fc65f8已完成实际双hash下载及新D完整源码/历史恢复。正常探索自然图、正式池/权重、其他命名模式和完整交付目标仍未完成。

已有[M33775研究](roguelike-finish-records-2026-10-23.md)已确定累计经验扣逐级成本的默认算法，并提供LevelPosition.in_level_exp；本次不重复该已通过研究，也不重算已有存档。尚须核等级栏和结果动画从property读取何种经验，才能确定修改应在领域存储还是投影。

本地官方metadata只读定位MenuLevelViewModel.LoadData M152771、_LoadNormalNextLevelInfo M152772、StatusBarLevelObject.Render M152529、RewardEntryLevelAndExpView._RenderExp M153415。第一次查询误用不存在return_type列，失败后只查真实列；宽查询含Expedition/Export，结果仅本地保存，已缩到四个相关消费者。四静态方法分别352/244/524/464字节完整线性解码，三只读页合计12288代码字节，分析ELF16384字节SHA256 9499422746c008b73a4760ab14b94aab07341381f79b5e71e96cd9bfdf8729e0，59完整seed。解码完整不等于语义或Hotfix已证；REA正在初始化，尚无新成功伪代码，不标结论。

基线保护源码、原生/QA保存、原种子、metadata/ELF及资源。旧审计保护的检查点索引只因本批已验证备份更新，旧索引字节在新checkpoint目录保留，当前索引与upload-verification逐字相等；其余保护路径保持。当前0新增Android/游戏输入/战斗/存档改写/EXE。证据.cache/rogue-exp-display-20261109。

## 2026-11-10：REA确认默认消费，投影修正进入验收

首次三页REA伪代码请求返回provider_timeout；随后续接原句柄丢失、Windows25064/11228及聚焦Linux进程缺席，无完成文件，不补报原退出0。doctor实际exit1，Ghidra12.1.4/Java/host/架构等相关检查健康，audit-wide因缺Hopper/IDA等其他引擎未全绿，本次不安装无关引擎。最初误把doctor的文本/YAML输出按JSON读而失败，原输出保留。

缩小至单页8192字节容器（352/244字节两方法、22seed）后，v2取得两个默认分支；v3两页12288字节（524/464字节、37seed）取得两个渲染方法。四证据：M152771 ev_bd27b0d957b836781541de270f94e0ae3a74d2c23d50685582de7f43cf7e426b；M152772 ev_47b1060ff54dab4ccc2ee25e475c3de75e3f07ecfd9f2088152291652d4e34f6；M152529 ev_32a8336609947de2a24c1867550fedb24789f71d193145610ddf9395d5412262；M153415 ev_c25c19ec22d3117757a89a5e4564f68ffc7a6ac998947ecda10db1a07ca354d1。原始伪代码只在本地。

metadata将Properties.exp定位+16、MenuLevel.currExp+28、nextExp+32；M152771默认路径直接复制exp到currExp，M152772按currLevel+1取等级表行exp到nextExp；M152529直接格式化二者并做比例，M153415直接格式化传入exp与nextLevel.exp。因此累计32/等级2对应级内22/下级成本24，而不能直接发送32。三个方法的Hotfix调用分支有missing-callee/bad-instruction截断警告，默认分支可见，不能说替换实现也已逆向；渲染方法M152529仅全局符号重叠警告。原生32/24与该默认消费一致。

v2关闭返回cleanup_incomplete，原因launcher短名java与绝对路径身份比较；包装/server actualexit0，聚焦Linux294/482及Windows20604/30996均缺席。v3close成功且包装/server actualexit0，Windows29868/29572缺席；独立聚焦ps无本项目REA或Ghidra分析行。research-verification实际exit0核4方法依据、旧194业务源码及全部保护输入不变后，才开始改产品。

当前业务abce9908/194Python/0037-78工作区未提交：只修改rogue_runs协议视图及roguelike适配，保留累计run.exp、旧结算effects/rulehash与原始收据。正值按已验曲线投影级内经验；初始化0经验不强行展开不相关完整等级表。新收据带内部in-level-v1版本并在回包时移除，防止重复扣成本；旧收据只在回发的副本上转换，不回填数据库。未知版本与畸形exp明确拒绝。

修前新集成反例10!=0保留；修后28不同针对性检查通过（v2的27+v3的1）。其间一个测试误把新0→0增量省略exp键与旧适配显式exp0要求字面相同，改为保留旧字段并核apply语义/其他字段/原始行不变，没有删字段迎合断言。88项受影响结算/新奖励/曲线检查通过；其余初始/招募/跨层/终局/战败/放弃检查14116仍在运行，已出现失败待终端详细结果，不提前记绿。

actual-v1/81784 actualexit0：实际完整28账号只改变28号视图exp32→22，级别2/其他全部用户字段保持；78原始表及历史收据字节全部不变，8既有战斗29报价保持，622条旧收据适配核对（其中3条正值经验转换）均不改保存。真备份/恢复、重开及新D恢复等价。尚0本轮原生输入，下一原生仅看已结束第四层地图经验，不开战/不领奖/不进入节点；当前不称视觉修复已验或新源码已在2fc65f8旧包中。

协议组14116已终止actualexit1，159通过6失败：0018旧结构夹具漏删0037新增表导致62而非61，改为正确还原旧61表、最终78表；旧空语音收据测试用存储JSON等于去私有字段后的HTTPJSON来定位，改为按当前账号及唯一revision定位后仍构造原旧收据并验证不写回；四条受伤通关断言仍期望累计10，改为显示0并另外断言持久累计10。只改夹具/断言，两个业务文件未再改。v6定点7通过（6失败及同夹具的旧结构回滚），保留失败XML/目录。

final-checks-v6逐个当前用例去重，28新针对性+88结算/奖励/曲线+165协议共281不同最终通过，Ruff7文件/AST194/diff通过。初始0经验完整表延迟展开、正值/边界/满级剩余、部分增量/引用清空、标志不泄露/不重复换算、畸形及未知版本拒绝、新旧结算收据重试/重开均有对应检查。完整实际保存证明仍上节81784，不因完善记录重跑。下一源码提交后仅用保留的第四层地图核22/24；自然供给和完整目标保持未完成。

## 2026-11-10：原生地图显示已修复，完整保存恢复通过

业务提交2ffbd1dbe55f587f0c1f34594668a3a2b9d3e7a6，abce9908/194Python/0037-78。只从上一已停机的QA28第四层地图复制新D保存，保留累计EXP32/级别2/生命4/金16/r26，未改引导或本地说明标志。旧硬件/index1/<test-device>/APK/资源/TLS/离线/8秒命令及root守卫保持，index0不动。

原生015-exp-map.png实际查看显示LV2 22/24，和修前029地图32/24形成直接反例/修复对照。013是新登录后的第四层介绍，seq14只点介绍启程，未进入节点；本次21HTTP全200，0条rlv2接口、0战斗/抽卡/领奖/说明接受请求。当前游戏进程错误级日志无Exception/Lua nil，仅限本次有界日志。未为补看奖励动画或满级而重打关卡。

原生包装25823实际exit0，自有ADB/server/worker全部退出且仅关闭index1。native-save-audit-v1/61966 actualexit0独立核PID缺席：完整28用户及78表真备份/恢复/重启/新D等价，登录只改变local_sessions，所有探索原始行/旧收据及其他27用户保持；累计32仍保存，8既有战斗29报价不变。证据.cache/rogue-exp-native-20261110-v1及本阶段native-save-audit-v1。当前无待续原生/REA/pytest/审计会话，未新打EXE。

下一保存本批私有回读检查点，再接正常探索地图/来源供给，完整目标仍ACTIVE。已关闭的是本次EXP显示缺陷的上述范围；新奖励动画、满级和Hotfix替换仍未逐项原生覆盖，正式图/自然池/其他模式/Golden/离线长时/性能/Harmony/成熟发行物保持未完成。

2026-11-10 EXP私有检查点完成：sourcec56e1ae/businessabce9908→private027cfc43da0c0ea42206d2cf828d6e2c1ee92858，parent2fc65f8/tree8902d09f8b8ab8ea24bee1250dd479b73f7cf94a。2757745bytes，SHA256 2b3b11837fd9cc72ba15675b34ce361fb970fb88842cbc8170550472925c0da3，Gitblob fd0dd94bbc9e78a8b46dcf3fa148ad32695947aa。private/ref/commit/tree/全文README/note实际回读、浏览器真实下载双hash、新D598源码279完整历史/tree/blob/Prompt/fsck/clean等价；600历史路径3131UTF8blob扫描无禁入/凭据。保留原231非README项/全文旧README，Git非交互probe128无ref，连接器expected_sha/forcefalse续main，不称源码分支直推。仅新下载双hash后从C临时下载目录移D，不改权限/凭据/8080/旧包/发行物。权威.cache/github-checkpoints/heartbeat-latest.json和exp-projection-20261110/upload-verification.json。完成文字晚于包，不重复包。当前无待续会话，下一正常探索地图/来源，保持全目标ACTIVE与不重打规则。
