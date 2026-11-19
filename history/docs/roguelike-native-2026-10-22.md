# 肉鸽原生连接准备与验收记录（2026-10-22）

目标是一次新的傀影初始化原生验证，不恢复旧剿灭、不重复关卡游玩。当前先完成启动器适配及新D盘QA准备；本节记录时尚未启动模拟器或游戏服务器，后续真实会话另追加。

## 启动器缺口及修复

cn-android-2.7.71-rogue-qa此前只有服务器协议别名/数据绑定。启动器expected_apk仍为它返回旧SDKv2 APK，installation_folder仍落到旧test-instance目录，Android.validate_configuration也没有本主题19表的明确分支。

新增8项反例中2项在修改前失败：启动器组件未拒绝肉鸽配置搭配旧18表/旧准备记录，以及ClientBinding未拒绝肉鸽配置搭配旧APK。Runtime本身原有的肉鸽指纹拒绝仍有效，不能把这个组件缺口写成整个Runtime已接受旧存档。

现在明确关联肉鸽配置、e915675d19表、已冻结SDKv3 APK 47356684...及独立test-instance-rogue-qa准备目录；不把两个19表指纹互换。其余版本、APK、资源清单、硬件、TLS、外网隔离和8秒Android命令检查沿用原有守卫。

56项启动器Android/连接生命周期检查通过，2.85秒，Ruff零，一项既有FastAPI/httpx警告。覆盖新配置的正反准备记录/旧APK拒绝、与剿灭/18表/未知配置的数据隔离，以及原有指纹、TLS、实例、有限凭据和连接恢复检查。没有重跑未受影响的旧关卡或1194全量。

## 新D盘QA准备

目录.cache/refresh-diagnostic/rogue-oct22-v1为全新67表存档、两个新本地账号，未从任何旧剿灭或产品数据库克隆。仅为账号1设置main_03-08一星开放资格夹具，标记首通奖励已处理以避免伪发；不是自然通关或领取。没有预填探索、干员招募、战斗、结局或奖励。

新配置使用复制的自有CA/本地准备记录与冻结bootstrap，官方数据、客户端资源和WebView资源只读复用D盘目录；不复制官方认证。BindingStore只绑定新的本地账号，有限本地SDK凭据由原启动器生成，绑定/令牌不入Git。

实际AndroidTransport.validate_configuration前置检查通过，没有运行ADB或启动模拟器。产品DB/settings/SDKv3准备记录、上一肉鸽招募QA存档及开发EXE五输入摘要保持。配置client_verified保留false；准备检查不等于真实客户端功能通过。

缓存QA控制器先核对真实CIM进程、源码摘要与实例租约，控制范围仅index1/<test-transport>/<test-device>。每个Android命令限8秒，截图后确认1280×720才允许坐标输入。只开TLS游戏监听18443，没有管理监听；请求日志不保存凭据，rlv2仅记录受限选项字段。QA明确阻止战斗开始，以免新号引导自动重放已测关卡；该拒绝不会被计为游戏成功。

停止时关闭自身服务/线程/ADB。只有本会话实际取得过租约，且清理时能重新独占租约，才允许退出具名index1；其他连接持有租约时跳过退出。准备/控制器语法检查通过，真实启动及清理仍待实际验证。

当前源码业务指纹a90ea8b7fee72ae7ce280451fa1a1af8ee4e0549d8c76d75a8c70e0a121c653e。证据为.cache/rogue-topic-20261022/map-research-v1/launcher-before.txt、launcher-after.txt，以及.cache/rogue-native-20261022-v1/prepared.json。源码检查点、实际进程和后续原生结果须分别核对。

初始化收尾/地图规则及持久化/节点/战斗、完整傀影主题和其他所有交付目标仍未完成；当前没有新EXE。


## v1实际会话与清理失败（后续记录）

来源ba1f031/业务a90ea8b7。实际源进程40832及启动器41380由CIM创建时间/命令行核对，连接只用index1；48个请求全200，SDK/U8、GS登录、syncData及本地说明确认后显示RogueNativeQA主页（1280×720）。实际截图确认全同步被消费，不能仅以HTTP200推断。没有开始战斗或进入肉鸽；新号触发首页/招募教程，按用户效率要求不继续重复原有招募/战斗验证。

源服务停止时，缓存QA脚本用text=True解析ldconsole list2，在UTF8运行时遇到其他实例的中文名称而报UnicodeDecodeError，随后listing=None的splitlines引发AttributeError，整体exit1，native-results.json未生成。控制端等待30秒后明确观察超时、没有重排输入；CIM随后证实40832/41380已消失且18443关闭。原始脚本/截图/请求及失败副本保留，不能把这次改写为正常清理通过。

两次独立清理恢复均保留了实例租约、硬件/APK/资源和8秒命令限制：首次设备尚未就绪，第二次已通过前面身份读取但APK摘要命令8秒超时，各自终止所属私有ADB后退出，未发送quit。当前CIM只见LDPlayer启动的共享5037 ADB30116（保持），没有私有nodaemon服务残留；index1仍运行。没有使用kill-server或改全局权限。它是QA清理失败与瞬时设备读取问题，不是肉鸽接口已测失败的证据。

停机只读审计67表，integrity/FK通过；账号1因登录、说明和首页引导改变8表，其他账号56表及五原输入保持。battle_sessions及rlv2_runs均0，尚未发生肉鸽创建/招募/结算。证据.cache/rogue-native-20261022-v1/stopped-audit.json及cleanup-failure-preserved*。

## v2精确引导夹具准备

新目录.cache/refresh-diagnostic/rogue-oct22-v2从v1停机存档复制，最初67表逐表相等，原v1保持。逐条核对冻结story_table后，仅加入l0-0的1_recruit_adv、2_make_squad、3_battle_ui三个已读记录：needCommit=true、disabled=false、无奖励/额外flags/关卡要求，进度链10→20→30→100。只更新账号1的flags.progress和revision以传递夹具；改动严格只有player_profiles/story_completions，不发奖励、不给干员或通关，也不将夹具当作原生完成。

v2控制器沿用8秒命令与租约守卫，清理时雷电列表改为原始字节decode(errors=replace)，语法检查通过。当前准备时尚未启动v2、没有新EXE。下一步跳过已验证的旧引导，直接观察肉鸽入口/初始化；目标仍是完整主题和全游戏，旧失效与未验范围不删除。


## v2真实入口观察与正常关闭

来源0f72487/业务a90ea8b7。源PID20076（CIM身份核对）、所属ADB5464/57512；初始NOT_READY在同一工作线程正常变connected，没有重启或放宽8秒限制。跳过三条无奖励旧引导夹具后，截图03主页、04终端、05集成战略入口、06/07六主题列表、08/09傀影开场、10傀影主页均被真实客户端显示。原新号/3-8资格仍为QA条件，不称官服自然新号解锁。

开始探索打开难度选择；上方正式调查、中央古堡观光及选择按钮，选择后返回主页，后续仍重新打开该面板。有限点击/拖动没有产生任何rlv2请求；不确定是交互方式、状态字段或客户端分支，不擅自归因服务器或伪造创建成功。没有开始/重复关卡，也未完成分队、组合、招募或地图原生验收。按用户时间安排停止重复点击，下一步转静态/REA查EventOnCreateGame和EventOnConfirm。

40个请求全200仅涵盖登录/同步、剧情完成与保活，没有rlv2请求；HTTP状态不代替玩法消费。native-results.json证明67表审计、56张其他账号表、业务及8份受保护输入保持；改变表仅player_profiles/local_sessions/story_completions/receipts/domain_events，battle_sessions=0。控制截图37首次观察返回运行句柄，后轮询同句柄正常得到结果，未重排输入。

停止后源会话49516终态exit0、QA结果owned_index1_quit=true/所属ADB退出，CIM复核20076及私有ADB不在、18443关闭，只剩共享ADB30116保持。v1失败和两个恢复失败副本保留；v2成功清理不抹去旧失败。无新业务修改或EXE，完整游戏目标及原生初始化缺口保持。证据.cache/rogue-native-20261022-v2/native-results.json、requests.jsonl和screen-*.png；下一检查点待实际远程回读。


## 难度入口REA定位（v2之后）

新缓存rea-menu/rea-menu-select按冻结ELF页及metadata地址准备，不读取客户端认证。M135957 EventOnCreateGame 0x39db1fc（580字节线性全解码）经REA/Ghidra12.1.4返回ev_51ab88caf3f04fd1fc04b92fb27783a67f2421f96cd5521ba76377885a012978，终态exit0：普通模式默认路径先读get_currentSelectDiffModel，空值则显示难度选择，不发送CreateGame；非空时取modeDifficulty/grade并调用Bridge.CreateGame。对应getter M134695实际汇编读实例字段0xb0，与metadata m_selectDiffModel一致。这里只解释可见默认分支，不当作现场变量已读证明。

M135648 EventOnConfirm 0x39cb2d4（284字节）返回ev_c2736c3c6cbdd2b86f11d14e8ca944b5bc0e715dbe8cf9f9d2c8eff176bd6a88/exit0，确认用当前pager索引查difficultyList，取mode/grade再调用受保护基类_SelectDifficulty。该基类M133942在磁盘176字节无法解码，未启动提供器，不能假称完整还原。M134698 SetCurrentDifficulty 0x398b7a8（404字节线性全解码）REA ev_a49278b8642f44305934e26349ec34e2c4508e6a610f9ef29ce7fce1788b4549/exit0，但Ghidra把外部barrier调用误判PIC、删掉后续块，伪码不完整；实际汇编有遍历候选、标识比较及status>=1分支，不能凭被删伪码改服务器。三个终端均exit0，WSL ps后无REA/Java进程，旧cleanup_incomplete记录仍保留。

复用此前M134701 _UpdateDifficultyList的既有REA结果，不重复提供器分析。metadata再次核对collect.mode是枚举→ItemUnlockInfo，modeGrade是枚举→int→DifficultyUnlockInfo，当前源码字段形状与此一致；不据此宣称本地实际反序列化状态正确。后续需完成基类选择调用/状态读取并核对客户端实际资源与导入版本，定位具体反例后再改业务。此次未为状态文档重跑已通过关卡或无关测试，完整目标仍未完成。
