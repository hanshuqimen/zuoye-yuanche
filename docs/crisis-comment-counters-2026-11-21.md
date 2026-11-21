# 危机合约 V2：快照计数绑定和评语条件

在[退出回执](crisis-exits-2026-11-21.md)之后补充必要计数、导入评语条件和只读通关准备。当前不写入通关终态，不授予奖励，也不开放新的原生路由。最终通关事务、纪录/回放及领取仍需接入，不能把资格计算标为完整可玩。

## 新的直接依据

只控制已准备的 index1，核对硬件、APK/ELF、资源、f441 数据、TLS 和 IPv4/IPv6 离线配置；每个 Android 命令仍限 8 秒。没有游戏 API 监听器。读取四个已命名代码页和一个只读字段偏移页，共 **20,480 字节**，没有读取堆中玩家、认证或活动 Hotfix 对象，没有客体 dump 文件。正常关闭 index1；index0 列表状态、宿主设置及保存指纹保持。捕获进程实际退出 0。

只读偏移表直接给出 BattleLogger.m_stats=0x30，BattleStats.charStats=0x18、enemyStats=0x20、extraBattleInfoStats=0x50、extraBattleInfoSubStats=0x58、extraBattleInfo=0xd8。这是该冻结版本加载后的声明偏移，不再根据文件中 1684300xxx 的保护值推算，也没有采用统一 XOR 规则。

三方法 **2,896 字节**完整用于新 REA 会话：M66437 TakeSnapShot、M66438 FilterBattleInfoStats、M66439 LogExtraBattleInfo。容器 SHA-256 `b1a6cfc8e76cdb38ece6d23684e66d5524667f2a922aa779958a376da262b08b`。三次返回非空正常路径，public status/close 成功、进程 exit=0、输入保持。Ghidra 的全局符号和异常调用限制保留，未宣称活动 Hotfix 已还原。

关键发现：运行时评论写入 **extraBattleInfoStats**，快照会把它复制到输出 **extraBattleInfo**。复制调用的静态 holder 对应 MethodSpec255759，即 `List<KeyValuePair<string,int>>.AddRange`，参数确认为源 0x50、目标 0xd8。不能把运行时字段名直接当作请求字段，也不能在后者缺失时用前者补零。

特定枚举的压缩默认值与已核的原生 box 参数、Enum/String.Format 调用一致，采用 `SIMPLE`、`ATTRIBUTE` 及 `COST`、`HP_RATIO` 名称组成键；不是把整数 1/3 拼进字符串。HP_RATIO 的 F3 文本按千分数精确读取。特定 EnemyStatKey.counterType 的 StringEnumConverter 属性另行核对；未知整数枚举不代替名字。上述是默认实现的字段/格式依据，**尚非原生危机合约网络包观察**。

## 源码行为

- 新计数投影只读取 charStats、enemyStats 和输出 extraBattleInfo。缺失/null 保持未知，显式空容器才是已知空。只保留已采用的事件/属性，不保存 access/hash、无关日志或完整遥测。重复组合、错误类型、数字字符串、错误前缀、歧义键和超过本地预算拒绝。
- ListDict 的普通集合形式与显式转换器的对象形式分别作为**两个明确的本地接纳格式**，生成相同规范事实并单列格式诊断；尚未证明本次原生调用实际选择哪个序列化设置。不会因 ListDictConverter 存在而宣称所有调用都输出对象。行数4096、累计计数100000是本地预算，不是官方上限。
- 评论组件按完整地图指纹绑定导入定义，支持首季实际出现的八种条件；按 sortId 排序。指定职业查看已绑定的开战编队；部署数直接复用已有真实格式证明的 SPAWN 池，不再猜一个额外阵容过滤器，也不把 DEAD/WITHDRAW 加作部署。
- 指定敌人的 HP_ZERO 与遭遇/到达出口分开；当前单一前置指标条件不推广成未知多指标语法。事件/属性条件要求游戏结束的 COST 标记，缺失不当零；生命比例的全体条件要求实际存在正次数的样本，不从空列表获得评语。规则是公开记录及匹配导入定义支持的本地解释，不是已逆向官方后端。
- 通关准备先绑定自有会话/数据/登录、结果、日志关卡及编队，再解析必要计数和职业。任何所需评语输入未知时明确拒绝，不静默跳过。开战前也增加评语编译，未知条件不能先插入战斗。微型 QA 图补了显式空 commentDataMap；这是夹具定义，不是删掉实际地图评语。

## 来源差异

[PRTS 玩家记录](https://prts.wiki/w/%E6%B5%8A%E7%87%83%E4%BD%9C%E6%88%98)可交叉检查职业取编队、实际漏怪门槛及自毁死亡的解释，但页面也提示条件准确性有限。当前导入的 `comments_0_8` 参数为 `4;5 / 110`，该页面写 220；没有用社区文字覆盖源表。当前信息来源和版本指纹保持，**该条官方匹配版本的阈值仍未证明**，不得标记官方全量规则已核实。

## 实际验证与下一步

169 个不同当前用例的最新结果通过：44 个新计数/规则检查、12 个新绑定准备检查、113 个受影响信息/存档/会话/退出/任务检查；本地预算检查在前置拒绝调整后单独复验，未重复全量。Ruff/空白通过。一次研究 rg 命令误带 PowerShell 选项已改为正确范围检索，不算产品失败。

冻结 20 表 `14457902…` 的新五图副本确认导入的 **22 条、8 种**条件全部编译；永久图逐项返回已知资格，四张临时图各按实际空评语定义处理。使用的是**人工加密请求、日志及计数**，未声称这些数值组成一次真实物理战斗。82 表全行不变、start_hash 保持，源及现用配置/保存/数据指纹保持。通关仍未最终提交，原生包与路由、分数/全部评语实际表现、领奖、断网长时和成品继续待验。

证据根 `.cache/crisis-20261119/`：`comment-counter-summary-v1.json`、`counter-source-projection-v1.json`、`counter-runtime-field-offsets-v1.json`、`counter-attributes-v1.json`、`comment-counters-v1/2/3.xml`、`clear-counters-frozen-v1/verification.json`，以及 `loaded-comment-counters-20261121-v1/`、`rea-comment-counters-v1/`、`mcp-comment-counters-v1/`。官方数据、代码页、伪代码、QA 保存和运行材料不入 Git。

下一以这些已绑定输入完成原子通关、规范结果/计数回执、分数纪录与历史保存，再接领取和原生路由。原生字段若仍有语义缺口，保存独立领域结果再依据消费者映射，不靠固定零值拼成功响应；完整交付目标保持。
