# 原版触摸输入的被动计数（2026-11-28）

目标仍是完整本地后台和全部模式。当前只用S4/614/SDK3既有300币账号定位原版列表拖动，不重打关卡，不造币或改商品排序。原版输入继续只由Computer Use提供；研究组件只读触摸记录类型，不注入进程、不产生手势、不读取官方认证，也不输出坐标或键盘值。

前轮cdaf363记录的元数据名称修正、13检查/冻结验证、四函数REA及2e71公开新恢复属于实际进展；本轮开始工作区干净，旧v6无进程，不按旧PID或live继续。可选手动对照尚未答复，不作为判断依据。

## 版本依据和最初拒绝

AOSP android-9.0.0_r61 InputDispatcher.cpp固定源码182959字节、SHA28b2c4c78f44d2ed391121163307c7b35ab78ede74ab154c623f350676c716cc显示RecentQueue仅用MotionEvent类别描述，不能由这个标准dump直接推出DOWN/MOVE/UP。原文只在.cache，不把AOSP版本冒充实测ROM源码，也不编造事件字段解析。

新增tools/research/android_input_probe.py接受已准入且持lease的现行AndroidTransport，复用同一ADB；保持设备/APK/资源/配置/TLS/离线守卫，限定实际API28/x86_64和已核触摸驱动能力。采集源为有硬期限的getevent，awk只输出五个计数和明确producer状态。缺少状态、早退、错误退出或异常输出拒绝，不掩盖为零事件；采样后核启动身份和同一游戏PID/起始ticks。正点击对照未成立时不能解释客户端输入。

初版假定GNU timeout的124，v7准备在执行计数脚本前拒绝。该假设未经设备验证，本轮撤回。借用当时实际控制器拥有的ADB子进程，用创建时间/路径/进程句柄核对，只读执行系统命令：false对照1，timeout 1 sleep 2实测142/1.062秒，路径/system/bin/timeout。实际help支持-k延迟KILL。未接5037、未停止父ADB、未再做完整APK读取或把这一步说成新客户端准入。

v7实际50295退出0/两回调SHA恢复/源保持；独立8秒实例回读确认index1停/index0保持。没有输入手势或采样，原始源码和失败文件保留。新版本先以timeout -k 1 1 sleep 3独立校准，只准入已证142或原124，采集必须匹配本次校准值并满足时长；5秒后附1秒KILL上限，所有Android命令仍8秒。22当前解析检查（覆盖显式142与任意退出码拒绝）及Ruff通过，初版17记录保留，不累加成39。

## 当前原版准备范围

v8实际71188/21172已核connected，复用同一存档，未修改旧实例/保存。已核完整准入、driver/所需命令和实际timeout142/1.094秒；独立guest脚本SHA d8b744053d2bb10493fadc4061ebf6c86679a77feb74b40b161a611ec2d77688匹配，准备通过。此时尚未采到正对照或拖动记录，不能说输入已验证。下一从正常主页以点击打开干员列表作正对照，若记录无对应变化则停止对计数的解释；只有对照成立才看一次拖动。

证据在.cache/crisis-20261128/aosp-input-contract-v1/source.json、native-timeout-contract-v1/{verification,timeout-help,transport}.json、passive-input-probe-tests-v{1,2}/junit.xml、crisis-s4-native-controller-v7/{input-probe-prepare-error,input-probe-source-used,completion,cleanup-current-readback}及crisis-s4-native-controller-v8/input-probe-ready.json。第三方源码、脚本部署回执和保存不公开；公开只含自有研究组件、人工夹具检查和事实报告。

## 测量窗口过期与新会话

v8第一份计数样本持续5.125秒、producer142、同一PID4129/ticks2304，五项计数为零。但采样与点击分成了两次工具调用，点击前窗口检查已过期并拒绝输入，实际没有发送点击。它只是无输入期间的计数结果，不是点击正对照，也不能证明输入丢失。expired-ui-window.json明确记录该失败；未补写input-action文件。

71188随后实际退出0，completion空错误、两个回调SHA恢复且源/现用保存保持。独立8秒ldconsole和保护文件哈希回读确认index1停、index0保持；cleanup-current-readback.json保留实际结果。新v9继续同一QA保存，实际73324/PID27964已connected，142/1.078秒和同一脚本SHA准备通过，最多四次样本用于容纳过期拒绝。改为先观察界面，再在同一动作调用中启动计数、等待就绪、发送一个Sky动作并立即刷新，尚未据此认定点击或拖动通过。

## 点击反例与停止解释

v9在00:16:06.805738Z启动五秒采样，Sky点击00:16:07.538Z至00:16:07.643Z，偏移0.732至0.837秒；即时刷新后，下一张新画面确实已打开干员列表。采样5.109秒/producer142、同游戏PID4134/ticks2915，但五项计数全零。时间重叠与进程稳定成立，计数源却没有观察到成功的界面点击，故正对照失败；不是点击未送达或客户端输入故障的证明。没有继续做拖动采样，没有再注入或根据零数改服务端。

click-control-verdict.json、input-action-0001.json及原始样本保留在v9目录。73324实际退出0、空清理错误、两回调及保护源/现用保存保持；独立8秒实例回读确认index1停、index0保持。组件源码保留为研究工具并明确这条已知限制，不作为已验游戏功能、输入诊断能力或运行时依赖。滚动、原版购买和完整交付仍未通过，下一转入未完成后台字段的冻结消费者依据，不继续重复无效输入诊断。
