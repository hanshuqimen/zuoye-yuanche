# 肉鸽候选无语音枚举纠正（2026-10-23）

## 现场及纠正依据

v5的难度选择/NORMAL0创建/分队/组合已实际消费。术师券激活200后未知故障；不把200当原生通过。v6完整复制其停机67表，保留同一Run和活动券，不重抽或重走初始化；源码仍356cc12e。客户端自动登录的GS登录/syncData均200，却显示“同步身份信息失败30000”。11请求200，无新增rlv2请求，改变仅local_sessions；正常exit0/index1及所属ADB退出，56其他账号表和20原输入保持。两份仅限当前游戏进程Error级日志的严格诊断均无异常类型/路径，不能宣称取得了具体反序列化堆栈；原日志不保存/不回传。

本地冻结metadata明确PlayerCharacter.m_voiceLan是不可空Torappu.VoiceLangType（偏移136），不是旧实现注释所称“nullable managed string”。枚举声明包含NONE、JP及各实际语言。Rlv2.RecruitChar/Char继承该字段。v5原候选中Amiya为JP、备用术师char_505_rcast为null；后者实际没有voiceLangDict/default项，不能伪造JP配音，也不能给值类型null。

因此撤回2026-10-22报告中“无语音备用角色voiceLan:null是合法客户端字段”的推断，保留其历史失败与源码检查记录；这属于源码确切合同错误。当时仍待原生；下方v7已实际确认这次现场恢复，不能推广为全部系统无错。

## 具体修改及旧存档

新备用候选用NONE，无语音判定仍要求冻结表同时没有语音和默认；有语音角色沿用原语言目录选择。持久化Character接纳冻结枚举，以及仅供旧数据读取的null；WireCharacter拒绝null和未知枚举。前置检查只允许明确备用/明确无语音的旧null，不泛化到普通干员。

已保存的旧候选不重写：只读投影将旧备用null转换为NONE。游戏协议边界另外只修复已知Rlv2候选/结果/局内队伍及招募结果路径中、明确备用且确实无语音的旧收据响应；保留原收据字节，不重新执行事务或发奖。普通干员/其他系统字段不做通用替换，未知值不默认成功。放弃探索的inventory/troop为合法null引用，适配器跳过这些成员。

## 验证及保留失败

新增三项旧反例失败：新备用候选仍为null、旧收据回放仍返回null、未知枚举被错误接纳。首次关联检查76通过/6失败，均是新响应适配器未处理放弃后的null成员；原失败保留，修正空引用遍历后82相关检查14.64秒/Ruff零/1既有警告。覆盖新候选、旧候选/旧收据只读兼容、Runtime重启及无DB改写、未知枚举拒绝、原有希望/重复/迁移/隔离/冷却等；不重复关卡和无关完整回归。

冻结真实19表的新v7目录：Runtime读取v6停机副本，2候选中1个旧null；完整同步投影JP/NONE，1份原收据转换，67表全部逻辑行保持，23受保护输入摘要保持。不是合成测试或原生通过。业务c463cea8af704fc02e7a410687a7adf1b1c8e645030af8c41dbb3c80e5f03afc，schema0020不变，无新EXE；这是启动前的只读检查，后续实际结果见下。

REA额外研究初始招募回调M161074：480字节可线性解码，提供器因cleanup_incomplete exit1，局部观察ev_75e6c8b89a56b90345602a6a30bb7961460ca50a078d282e2bdb2c332871042f单独保留，WSL ps后无REA/Java；不记完整成功，也未据此猜改pending或候选ID。其他候选字段和招募完整视觉仍待原生。

证据.cache/rogue-recruit-native-20261023/voice-before.txt、voice-after-first.txt、voice-after.txt、rea-init-response；.cache/rogue-native-20261023-v6/native-results.json、screen-02.png、errors-*.json；v7 legacy-wire-probe.json及prepared.json。资源/存档/日志/官方声明均仅本地。下一步在当时为同一活动术师券验证；结果见下。完整主题、地图/战斗/奖励/结局及全部交付目标保持未完成。

## v7原生结果与停机复核

2026-10-23 v7实际通过原生登录恢复（30000消失）、原活动术师券候选、阿米娅招募、无语音预备干员-重装char_514_rdfend零希望招募及最后狙击券放弃；正常动画/两名干员/希望3/三券DONE/“进入古堡”可见。61请求200、5个rlv2请求；未点finishEvent、未进入地图或战斗，没有重复初始化/旧关卡。正常清理/56其他账号表与23原输入保持；新D Runtime重开67表及完整rlv2等于最后快照、原存档字节保持。来源fcbd6c2/业务c463cea8；这只证明该普通/备用/放弃分支，完整主题仍未完成。

此前null候选确为客户端兼容错误，本次仅改语音合同即消除30000并消费原候选；不宣称捕获了具体客户端异常栈。两个既有候选/旧收据仍通过只读适配，未重抽。无语音备用重装最终ID以SQL联表为char_514_rdfend，与screen-13和screen-17画面一致，不采纳上下文摘要的错误猜测char_506_rdef。

证据为v7 reviewed-results.json、rlv2-0058.json、screen-05至17及reopen-verification。当前服务/启动器PID24652/18744已由CIM复核不存在、18443关闭；未触碰共享ADB或index0。后续地图草稿/schema0021变化未做新原生，不把v7的源码c463结果自动推广至新业务。
