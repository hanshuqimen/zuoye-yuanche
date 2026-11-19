# 属性收藏品的新原生代表（一次代表及恢复通过）

源码业务23b6f143/schema0033/74表；49条接口检查及私有2a146b5/83b2627实际回读已完成，范围见[源码报告](roguelike-battle-attributes-2026-10-29.md)。完整目标未完成。本代表只核对一个新的属性效果/战斗消费者，不重新游玩旧ro1_n_1_1、ro1_n_1_4、ro1_b_6，不恢复取消剿灭。

固定CN Android2.7.71/19表e915675d8d8a1cc97df8fa46eed27ef1bdaa9d1b0fdb07461dcabda36271ae29。仅index1/<test-transport>/<test-device>，APK/资源/数据/硬件/TLS/离线/8秒守卫保持，index0保留。没有新安装/协议万能响应/管理8080访问。

新D Sandbox19（BattleAttribute19）为显式QA：准备进度入口/引导条件、两名预备干员、三列SHOP→BATTLE_NORMAL ro1_n_1_2“驯兽小屋”→SHOP，以及索引0/价格1/单件无叠层a11异铁小圆盾。此地图/商品/价格不是自然供给或官方权重；仅真实客户端后续点击才记原生购买/战斗。已通过匹配区域准入，目标未出现在继承保存的任何战斗stage_id中；准备10HTTP200，未创建新战斗，旧18完整用户逐字段保持，183保护输入摘要保持。副本新建，未覆盖旧保存/发行物。

基准来自实际导入表与保存模板：预备近战char_504_rguard精一55、潜能0/信赖0，无天赋/潜能条目，当前阶55级DEF278；预备狙击char_507_rsnipe同阶55级DEF115。a11配置为def +0.15乘算；对应未取UI显示舍入的数值为319.7/132.25，不先猜显示整值。最终必须用当前原生画面/实际购买记录核对，不能由表值或HTTP200宣称效果生效。

本地准备`.cache/rogue-attributes-native-20261029-v1/{prepared.json,prepared-state.json,prepared-users19.json,attribute-reference.json,native.py,control.py}`；运行数据`.cache/refresh-diagnostic/rogue-attributes-native-20261029-v1`。准备39876实际exit0，native_not_started=true。首次读取参考统计遇到talents=None，仅读取按实际空列表处理后得到上述基准，未修改数据。

下一步以当前完整Git HEAD启动唯一源worker；一条输入ACK后至少3.5秒、截图并查看，再下一条输入。只允许本目标stage的新战斗，已完成战斗不得再开；来源代码运行期间冻结。实际进程/会话优先于本段准备文字，观察超时不重排输入。完成或失败后正常停止自有服务/ADB/index1，再核旧用户/74表/保护输入及新保存重开/恢复。


2026-10-29实际启动：源HEAD7c564b429a7a3029ec26f169c6bbd2c0c1ddf947/业务23b6f143，统一句柄12812、当前验证PID13112；仅index1，已connected。首次短暂黑转场自行到登录，未按Back；本地登录正在加载，最后输入seq7、截图seq8/screen-04。尚无新原生购买/战斗。恢复先核实际句柄/PID和ACK，不按准备标志重启或重排；业务代码冻结。

## 实际代表与停止后验证

2026-10-29新属性代表已收尾：仅一次新关ro1_n_1_2，无旧关重打/剿灭/新招募/部署。原生购买a11异铁小圆盾，源石锭6→5、售罄及库存图标正确；战斗预览DEF320与基础278×1.15取整一致。自然失败后battleFinish/gameSettle各一次200，回到主题主页，62HTTP200、定向异常日志0。旧18完整用户保持，当前19用户/74表在重开、真实备份恢复及新D恢复均相同，183输入保持。12812实际exit0、13112缺席、服务/自有ADB/index1正常停止，index0保留。业务23b6f143未改，没有新EXE；49条已批量接线不等于逐条原生已验，显式QA地图/商品/价格不证明自然供给。下一转自然节点/商品供给规则，0追加游玩；完整目标未完成。

seq27输入与seq28截图在上次观察输出截断后已按ACK及screen-15恢复核对，未重复输入。随后商店详情screen-18实际写明所有我方单位防御+15%；seq35购买后screen-19显示售罄、金币5、收藏品1。进入唯一新关驯兽小屋，screen-26为实际战斗中选中尚未部署的预备近战，显示LV55、防御320、攻击309、生命1165；原基准278和选择器来自实际匹配19表/模板，未用HTTP200推断效果。没有部署或额外招募；切2倍后自然失败，没有giveUp/interrupt，也没有重开此关。

实际battleFinish编号61：completeState1、percent6、killCnt/validKillCnt2、completeTime59、leftHp0，journal存在、snapshot动作0；finish-facts SHA256873c980fb8df2fe1803aa1d402da8e7d4d1e5ab4bc0e1052580b0844c865aa09。gameSettle编号62，最终11分/+11蜡烛/+1灵感，screen-36返回主题主页。结算页招募次数4包含预先QA准备的记录，不能记作本轮4次原生招募；本轮原生招募0。没有从单一预览推广为全部49件/选择器/Hotfix逐项原生通过。

seq66保存最终summary，seq67定向当前游戏进程异常诊断0；stop正常结束唯一worker。12812实际exit0，独立验证98382实际exit0。verify.py逐项核源168文件/183保护输入、进程缺席/TLS端口关闭、一次开始/一次完成/一次结算，旧18完整用户不变，19用户/74原始表在服务重开、BackupService真实备份恢复和restored-new-d-v1新D恢复完全相同；SQLite integrity/foreign_key检查通过，59其他账号表投影保持。只核新增代表的证据缺口，未重跑已过163检查或旧关。

证据仅本地：.cache/rogue-attributes-native-20261029-v1/{verified-native-attributes.json,verify.py,native-results.json,requests.jsonl,finish-facts-0061.json,deployment-stats-0061.json,summary-0066.json,errors-0067.json,final19-users.json,reopened19-users.json,restored19-users.json,restored-new-d-v1,screen-18.png,screen-19.png,screen-26.png,screen-34.png,screen-35.png,screen-36.png}。原生画面、保存、收据、官方资源及本地协议细节不纳入Git。最新私有源码检查点仍2a146b5/83b2627，本次报告晚于该包，不声称已包含或仅为记录重复打包。
