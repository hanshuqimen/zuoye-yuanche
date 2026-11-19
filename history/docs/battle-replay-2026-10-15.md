# 普通战斗代理读取与模式缺口

当前开发重点按用户更新后的目标转向抽卡、普通战斗/代理、集成战略、卫戍协议、剿灭与危机合约，保留原生视觉、持久化、离线及稳定性要求。普通代理的一个接口补齐，不代表这些系统已经可用。

## 本次已确定的问题与修改

原代码只注册battleStart、battleFinish、saveBattleReplay，没有读取路由；isReplay=true仍明确返回BATTLE_MODE_UNSUPPORTED。保存记录虽然能在syncData中显示hasBattleReplay，实际读取和代理开始并没有完整实现。这是可以从当前源码直接复核的功能缺口。

已增加`POST /quest/getBattleReplay`，接收stageId，使用当前账号的游戏会话鉴权，以只读事务返回其原始battleReplay和空增量。读取不创建幂等收据、不恢复理智、不发奖，也不会因客户端复用序号返回旧一代记录。完整代理开始仍待实施和原生验证。

读取检查记录版本、GameData、原始字节指纹、对应的非演习三星战斗、ZIP/JSON格式及关卡关联。损坏的已保存数据返回明确错误并保留原记录；没有记录时不返回伪造的空成功。同步时仅进行长度/ASCII/指纹检查，实际读取才解压，避免每次普通API都解压所有代理日志。没有把旧本地events对象当作原生记录。

25项代理专项检查通过，完整905项检查通过（226.82秒，一项既有警告），Ruff零诊断。新增检查覆盖并发只读、当前代替换、重启、账号/会话隔离、非法字段、损坏指纹/档案、错误关卡、旧版本、演习及非三星战斗。实际客户端读取、代理开始、代理战斗和新EXE尚未验收；后续不能仅凭这些合成检查宣称通过。

## 路由与字段的冻结依据

CN2.7.71的索引声明LoadBattleReplayRequest（type1613）只有stageId字符串；原拼写LoadBattleReplayReponse（type1614）继承PlayerDeltaResponse，新增battleReplay字符串。声明本身不证明所有JSON别名或执行行为。

ServiceCode.LOAD_BATTLE_REPLAY字段35485的field-default指向值区索引106771、原始元数据偏移20811827。此处首字节0x2c对应长度22，后续22字节为`/quest/getBattleReplay`。相邻SAVE_BATTLE_REPLAY字段35484同样绑定已经实际使用的`/quest/saveBattleReplay`，为压缩字符串解释提供对照。研究没有访问认证资料或玩家堆；不把未覆盖代码称为完整逆向。

冻结索引SHA-256为`30c555d4479d4a0f708b9fc61aa4ecfeb945a169e4a82586e31d243afdaa4804`，元数据为`bf14421bbafe9c71d944ba4f97b31ecd666232640eac0829db3d84ac716ac8b8`。本地选择性证据在`.cache/rea-2026-10-15/battle-replay-root`，官方载荷与代码页不上传源码仓库。

## 其他指定模式

当前18张已接纳GameData没有roguelike、autochess、campaign、crisis的独立核心表。数据库中的RoguelikeRun、RogueNode等实体没有对应的原生可玩流程；不能以有表结构证明集成战略实现完成。现有原生开战仅接受明确适配的普通MAIN/NORMAL/NONE，剿灭和危机合约不能直接作为普通战斗成功返回。

冻结activity_table中可定位卫戍协议的act1vautochess，以及卫戍协议:盟约的act1autochess/act2autochess。冻结程序具有AutoChess的训练、组队、匹配与对战请求；这些不是现有普通quest接口的等价替代。仍需闭合HTTP与实时服务边界、核心状态、匹配与本地对手、资源引用及实际原生体验。

后续按原生合同完成普通代理保存/读取/开始/结算及重启，再推进剿灭的击杀档位/奖励和周上限、集成战略的完整主题、卫戍协议、危机合约；抽卡的剩余池型、保证和原生流程亦继续审计。Golden Playthrough、完整断网、两小时、性能和HarmonyOS验收保持未完成。商店旧验收和回滚点保留，本轮不继续仅服务旧商店重点的新增工作。
