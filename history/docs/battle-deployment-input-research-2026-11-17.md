# 战斗部署输入研究

完整目标 ACTIVE，尚未完成。本阶段为 QA39 未部署成功后的只读研究，不重打 ro1_n_2_3 或其他已玩关卡，不把手势 ACK 当作部署成功。业务仍为 8fa55847、203 Python、schema0037/78 表；没有新业务、模拟器操作、玩家 Runtime、存档写入、检查重跑或新 EXE。

## 证据与恢复

只使用已冻结 CN2.7.71/V070 文件：metadata 索引 SHA256 30c555d4479d4a0f708b9fc61aa4ecfeb945a169e4a82586e31d243afdaa4804、libil2cpp.so SHA256 3ece1e7b34165233fe8c3c919cf55dfcb4406b6bbc2725def2b1242b4c0a6259。游戏表仍是实际 e915/v077/77.6.0、client_verified=false，不能据此声称所有客户端/表同版。本阶段没有读取匿名内存、堆、官方认证或浏览器凭据。

旧 mcp-deployment-v1 仅保留 initialize 请求，没有响应/ready/关闭结果；65301 句柄已不存在，真实查询原 Windows wrapper35720/child28544 均缺席。保留旧现场，recovery-20261117.json 记录旧退出未观察，不能补写成功或 exit0；没有重复原命令或杀无关进程。

新 mcp-deployment-v2 从真实 initialize/tools/list、open 和六次 procedure_pseudo_code 返回取得结果。六目标均在两页已初始化代码内，逐字节完整线性解码；分析文件12288字节、SHA256 96c3db12385a9704a4160cccede3811aebad2bbf270e0e3119991d51b00906c6，代码 SHA256 8d40e5b0655c2fa2b487cfbd69ff9f88565564e4caec4a07eb6845242141e5cd。外部调用只加15个已核标签和未初始化只读页，不填造函数或 RET。

| 方法 | RVA / 完整字节 | REA evidence |
| --- | --- | --- |
| M100986 UICard.OnBeginDrag | 0x30e2e94 /356 | ev_dd452cf678ef852696c4f78a72a08fbccca58facb5bd011923236a5f77f7c331 |
| M101065 UICardList.OnBeginDrag | 0x30e2ff8 /260 | ev_52c8718bc801db8a3ea84ea8bab262303e7c16a0a4a47cc83154f4e37ea3ca0d |
| M100984 UICard.OnDrag | 0x30e2a58 /288 | ev_5a7a1f21bd3cdf7ec80b1ef519c7d9f36e01649f0c4eaaf3fb5712df92d378ea |
| M101064 UICardList.OnDrag | 0x30e2b78 /184 | ev_5b39e016fcbfea6aeddd27145c95a1e60e5315f0eddf900ff269f46e137a7c0d |
| M100987 UICard.OnEndDrag | 0x30e30fc /288 | ev_c9ed703fe262aff2f3ade43ea8f2427e7c9a506433f1461bb2116f6859d2e652 |
| M101066 UICardList.OnEndDrag | 0x30e321c /228 | ev_27e3d755d51ef6745254d7e4b16751932b52a89233c75f09878848094b6633d1 |

## 已读到的有限结论

以下均为冻结代码中未被 XLua delegate 替代时的分支；没有观察运行时是否装载对应 hotfix。

- UICard 三个入口调用 FilterPCBattleInvalidClick；开始拖动额外检查 disableDragCard 与 disableDragCardForced，满足后向卡片列表转发经过 PointerEventData 类型检查的事件。仅这些检查不能证明暂停是否禁止部署。
- 列表开始拖动检查卡片 isEnabled，调用 set_currentPointerId 写入事件值，再调用 UIController.OnCardBeginDrag；结束则调用 UIController.OnCardEndDrag。不能把这些转发调用等同于部署完成。
- 列表三个入口还通过对象字段及虚方法表转发事件，反编译保留未恢复的间接跳转警告。尚不能仅凭字段名/偏移指认该对象的运行时目标或据此改服务器。
- metadata 中 UICard/UICardList/UIController 的字段 offset 明显受到保护，例如重复0x64646464及相邻巨大值。字段名称只作候选，不把这些值当真实结构偏移，也不据此读取内存或硬配字段。

六函数没有确定 QA39 失败原因。旧 QA23 实际成功的两阶段拖动/SPAWN1仅为复看证据，不重玩；QA39 的 charStats 空、snapshot_actions0与 q21 消费未证实结论保持。

close_binary 返回 cleanup_incomplete，而包装进程93052实际 exit0、子服务 exit0，分析文件未改变。按错误报告仅核 WSL PID571 已不存在，真实 Windows wrapper/child均不存在；deployment-rea-cleanup-v2.json记录0杀进程/0Android，并保留关闭错误，不将其改称无警告关闭。

## 下一层研究（进行中）

只读 metadata 候选已定位 UIPlayingState/UIShowCardState、UIDragAndPutDownState 和 UIController。新提取17个完整目标，覆盖拖放开始/结束、落点判定、坐标转换、更新、朝向选择及两个状态回调；101个同页完整函数作为标签。初始化代码6页，文件28672字节，SHA256 b2c58ba4c2b0948b9c36e3e837edd7b45572c3e672ed82e6667c547f14919857，初始化代码摘要 b3abf28c242d73db62271846ab53fb2e04c63a67029871563b12ac9592818365。85外部目标只加标签/56未初始化页，不合成行为。

新会话 mcp-deployment-state-v1 尚待读取结果。曾在 ready.json 尚未生成时调用请求辅助，辅助在读取 ready 前失败，没有写 command 或发 RPC；随后确认真实 ready 才提交 open/首个函数，沿同一会话等待，不重复初始化或请求。不得把 pending 或辅助观察超时改成 RPC 失败。

可重复入口：先读 live/ready/in-flight、实际拥有进程及已有 command/ACK；已有 ACK 后运行 read_deployment_state_rea_v1.py 对应序号，下一请求按 static-diagnostic.json 的真实 RVA 使用 ask_deployment_state_rea_v1.py。所有结果仍待结合完整分支和原生实际反馈，不预写可部署或 q21 生效。研究完成后再决定是否需要一个未玩关卡的代表，不盲目新战斗。

本地证据目录 .cache/rogue-global-native-20261112：deployment-consumers-20261117.json、deployment-input-candidates-20261117.json、deployment-state-candidates-20261117.json、deployment-state-methods-20261117.json、recovery-20261117.json、deployment-rea-cleanup-v2.json、rea-deployment-v1/v2、mcp-deployment-v1/v2、rea-deployment-state-v1/v2、mcp-deployment-state-v1。原始指令/反编译/官方文件/运行日志不进 Git。

## 已读完放置路径和冻结配置

同一 mcp-deployment-state-v1 会话17个目标取得REA响应，另从同一工件的完整既有种子补5个构造/初始化/快速操作消费者，共22次 procedure_pseudo_code。先读 ACK 再读结果，没有重排首个52.610秒请求。91065收集辅助实际exit0；最后close工具成功、40582包装进程和子服务均实际exit0、文件未变，真实拥有进程身份缺席，无待续REA或原生会话。

完整线性解码不代表完整可用反编译：M102008状态点击回调的尾部目标在未提取页，M101939初始化的Hotfix分支及M101968快速操作_CheckValid有bad instruction/截断；保留这些结果，不用它们证明当前Hotfix、点击效果或快速操作资格。其他间接/全局重叠警告仍见逐份findings。最初把两个状态点击回调纳入候选，并未因此取得部署证据。

已核未替代分支：UIController开始/结束拖动向事件池发送3/4；UIDragAndPutDownState开始还检查功能掩码、插件、状态、禁拖与引导条件。禁拖getter会调用isPausedButNotInGuideMode，快速操作可能请求解除暂停，但其完整资格未读出，所以仍不写“暂停必定不能部署”。_TryGetScreenPos从当前卡片pointerId读取光标；_UpdateInternal核CameraController.IsValidPut、具体格可建造和距离条件。结束拖动把当前格交_PutDownInternal；格为空或输入无效返回默认状态，满足才显示朝向。_OnDirectionSelected确认后才调用PlayerOp_Spawn。

关键REA：开始M101936 ev_a0f6f9f7506eedd6d2db923c57ca77b151f6060e265183b2063f0bad60069b04；光标M101947 ev_b7514949b95e0641a1e2ac48a1988beac1f7983a55a51fb8d567271f95bd0c8c；更新M101948 ev_b9d3ff7db245bc0a84540b921437f8bbd3d06d5a57473071266184f0a3165f3d；落点M101945 ev_832f6e070df0071058b5fe676c9556bef2b6823e15b2dfd132643cd5f43c1cd9；朝向M101949 ev_0e262cad6b5e248dba36ea2b5245caf373710d1e5d454995edacb60fa759e8ee。全部22份索引见deployment-research-final-v1.json，不以函数数量当功能验收。

M101953 _ConvertScreenPos的浮点伪代码只显示一个分量，ev_4ce791e2ebdc19633f7bd05fde84341d1b1b6ff640aa1582a1eb1d682f6d88c7不能单独用于计算。逐条核ARM64在0x3126900..0x312692c取屏幕宽/高、读对象0x2c/0x30、分别相乘再与原x/y相加，确认两个分量。这里的偏移来自实际指令，不是把受保护metadata字段offset当真。

构造函数只给字段默认值，不能替代实际序列化实例。先解析基础APK battle/[pack]common.ab，758726字节/MD5 e91713ef9928eb970dc37b62cd9b3c0d，与冻结清单1025969字节/MD5 f2c2514f8e45a84eace81cd64c7efd06不符，明确保留为基础包证据而不推广到运行资源。29组71,277,885字节内置资产字串定位仅globalgamemanagers.assets含类名，未找到触点字段；这是有限负结果，不是字段缺失证明。一次生成v2脚本的精确文本替换断言失败，未生成/未解析，随后按实际read(info)修正，保留失败事实。

随后只读已有D盘冻结battle_[pack]common.dat，无新下载；ZIP830468字节，SHA256 ec6ea67370ed2b5f579f2be4432bff79dfe95948af342dda7aeeb79de5d7e30f，verify_archive验证成员名称/大小/MD5。成员1025969字节，SHA256 7b54b0ad600e909b011a30a1badfdfaf665f2b9523512be0f17928f87b206c16，与资源26-09-22-07-47-20_6c71fa清单d1ac02a6完全匹配。3348对象、135种MonoBehaviour结构，55本地路径；没有触发全局container或加载外部依赖。

ui.prefab根控制器的_states明确引用state_drag_and_putdown组件，后者内嵌类型树/实例给出_tileLocateRadius=0.4000000059604645、_touchOffset={x:0,y:0.029999999329447746}。v3本地PPtr链已核，不是仅按字段名猜实例。对于720高的屏幕，触点正向Y偏移约21.6像素；Android左上原点下，要使转换后的点落在所见格心，手指目标Y应比格心大约21.6像素。还须使用当前放置相机的实际画面、留在格心容差内，再确认朝向，不能把屏幕上任一点自动当合法格。

复看QA39的039/041旧截图确认第三次swipe目标未经此补偿，存在落点偏离格心的可能；没有重播。**尚未证明该偏移就是QA39唯一失败原因，也未证明当前Hotfix不覆写参数、成功部署或q21技力消费。** 不因此改服务器判定、放宽原生守卫或补成功回包。下一只准备一个实际历史未玩关卡的新QA副本，采用有资源依据的手势换算；先按真实保存查重，成功仍需画面/Spawn/技力证据。

finalize_deployment_research_v1实际exit0：203业务源码和46保护输入全部保持，39账号78表/26肉鸽/0普通战斗未变。权威deployment-research-final-v1.json与deployment-battle-common-v1/v2/v3.json、deployment-serialized-field-locations-v1.json、deployment-state-extra-whitelist-v1/v2.json及mcp-deployment-state-v1结果；0新业务/Runtime/Android/存档写入/检查重跑/EXE。最新已验证远端仍sourceef90050→privated28fdea，本轮只有文档，后续业务检查点一并保留，不重复纯文档bundle。
