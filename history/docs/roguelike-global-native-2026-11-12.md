# 全局技力效果原生代表（消费未证实）

当前：一次新关已自然战败并结算返回；没有成功部署，技力效果未通过。39用户78表恢复已核同，下一先研究部署交互，不重打本关。

## 启动前准备记录

完整目标ACTIVE未完成。上一42项普通全局效果已在源码ef90050/业务8fa55847及私有d28fdea完成141检查、38用户78表恢复与完整源码回读。本阶段只做一个新原生效果代表，不逐件测试、不重打旧关；自动检查和原生消费仍分开记录。

读取真实19表e915/v077/77.6.0/client_verified=false，对冻结CN2.7.71/V070不称全表同版。选首主题rogue_1/NORMAL0/冻结时钟1792645099；效果q21为单一global_buff_normal，黑板为攻击/受击回复技能每1.5秒补1技力。自有新Vanilla QA39仅招募E0 Lv1克洛丝，其第一技能数据为INCREASE_WHEN_ATTACK、初始0/消耗5。只观察无攻击条件下的技力变化，尚未验证实际消费或精确计时。

第一准备候选ro1_n_2_1“压轴登场”在实际保留战斗表中已出现，prepare_native.py在创建HERE/QA副本与Runtime前断言拒绝；未启动模拟器/未开战。不以账本搜索未命中当作未测试证据。selection-v2枚举真实历史14个唯一关卡与当前第二层候选，选实际未出现的ro1_n_2_3“落魄骑士”，levelId Obt/Roguelike/RO1/level_rogue1_2-3，并通过当前区域安置合同；2_4/2_5留待其他必要新代表，不臆造首区第六关或套紧急变体。

prepare_native_v2/82954实际exit0，D盘新副本原38完整用户先核同。仅新增QA39，按实际API完成初始招募，再保存明确两层配方：第一层单行商、第二层单新普通战斗；零价格q21为显式QA来源，购买与离开行商通过正常API推进到第二层WAIT_MOVE，没有直接改游标或伪造战斗。13次HTTP200且增量一致，原38完整用户与所有旧行保持，原25肉鸽战斗/0普通战斗保持；新账号0战斗。库存仅初始藏品与q21、探索阵容仅克洛丝。初始六个已知引导标志只在QA39按已验证QA38值准备；不因此完成真实新玩家引导或接受官方协议。

运行工具复用当前默认图验收的拥有权/8秒ADB/硬件/APK/资源/TLS/断网守卫，只控index1/<test-transport>/<test-device>，index0及原保存保留。新守卫仅允许上述新关一次战斗及必要结算/关闭请求，普通关/剿灭/寻访/新建探索被阻止。每个输入需真实ACK，截图前额外保证至少3.6秒；画面须实际查看后才投递下一动作。新会话尚未启动，未标原生通过。

本地证据.cache/rogue-global-native-20261112/{selection-v1.json,selection-v2.json,prepare_native.py,prepare_native_v2.py,prepared-source-v2.py}；.cache/rogue-global-native-20261112-v2/{prepared.json,prepared-state.json,prepared-users39.json,consumer-reference.json,fixture-http.json,native.py,control.py,send.py}；运行数据.cache/refresh-diagnostic/rogue-global-native-20261112-v2。原始表/保存/会话/绑定/客户端/图片/日志仅本地不进Git。0新业务/本批检查重跑/Android/原生/战斗/EXE，下一一个效果消费代表，结束后恢复核对与及时更新账本，完整自然供给和所有其他模式继续未完成。


## 已结束代表与未通过项

本轮业务8fa55847/203Python/schema0037-78不变。原生worker53280实际exit0，实际运行文档HEAD8cd2a5bb204008e3afcb5f5e0f9498eb6d5ad8f8。001 EMULATOR_STARTING后同一会话002连接，没有因首个状态重启。003登录加载、004已经QA39主页；客户端自动本地update_agreement200，没有展示/勾选官方协议的模型动作，不把旧QA27确认挪用为本轮官方接受。

014真实显示皇家利口酒、攻击/受击回复技能每1.5秒回复1点技力；018落魄骑士、020地图、024退出预览、026唯一克洛丝、029战斗已加载。021 Android back后022预览短暂为空，023点外部区域后024回关卡信息；022/051文件名只是预期动作标签，不能据此声称当时已关闭/回主页。029战斗生命8=本局生命4加初始分队临时4；初始分队只有level_life_point_add，没有另一个技力效果。

030暂停后032向顶部平台swipe、034恢复后036再次swipe、038点选角色后040swipe均没有产生部署/朝向确认。039确实显示绿色可部署格、左侧角色面板和相机位移；041回到未部署状态。不能从这些画面断言暂停禁止部署，也不能未经函数核对归因服务器或客户端代码缺陷。动作ACK只证明Android命令完成，不能证明游戏接受了部署。042意图暂停时已结束，043为载入过场，044战败结果。typed finish completeState1/leftHp0/killedEnemiesCnt0/fixedPlayTime81133、charStats为空、snapshot_action_rows0明确没有成功部署。预定“无攻击技力增长”没有发生可观察见证，q21战斗效果仍未验证，不重打本关补造成功。

044战败结果保留克洛丝1名和q21收藏品1件；049分数39/蜡烛+39、051古堡笔记39/200及灵感+3、053真正返回可开始探索的主题主页。实际69HTTP全部200但含轮询，仅/rlv2/moveAndBattleStart、battleFinish、gameSettle各一次；没有额外战斗/寻访或QA拦截。22次输入=18tap/3drag/1back，27个PNG均逐次实际查看，输入ACK后至少3500ms再取图。最后当前游戏PID日志Exception类型空、Lua nil0，仅为当前PID筛选边界。

audit_native.py初版误把输入数量写23，实际为22，断言在打开新玩家Runtime前拒绝；失败目录native-save-audit-v1及脚本保留，v2按真实已查看序号集合核对。audit_native_v2/18748实际exit0：完整39用户78表真备份恢复/冷重开/新D严格同，原38完整用户及25旧战斗/所有旧行保持，当前26肉鸽战斗/0普通战斗。新QA39已SETTLED且无当前玩家/待处理，q21发现state2持久保留；46保护输入及203业务源码保持。实际workerPID缺席，自有ADB/服务/index1退出，index0原列表相同。

权威本地.cache/rogue-global-native-20261112/native-save-audit-v2/{verification.json,full-users39.json,restored-new-d}与native-v2的图片/ACK/请求/typed facts；原始数据不进Git。本轮0新业务/EXE，未为文档重跑141未受影响检查。当前仅库存/描述/新地图与战败结算/持久化消费通过，技力实际增长未验，完整主题与所有成熟交付目标继续未完成。

对照已验旧QA23的实际commands和guard-placement-02图：当时一次swipe进入朝向，再另一次swipe定向并有SPAWN1；只是复看证据，没有重玩旧关。下一先核UICard/UICardList的OnBeginDrag/OnDrag/OnEndDrag和相机/点击状态，避免在计时战斗中盲试。只读metadata索引30c555d4按类型连接得到349相关类型/81名称候选，实际普通UICard目标M100984/100986/100987及列表M101064/101065/101066；含其他玩法/接口候选，不把名称当函数行为。deployment-targets-v1.json仅定位，尚无新REA会话或新输入。
