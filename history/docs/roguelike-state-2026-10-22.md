# 现代集成战略主题状态与置顶（2026-10-22）

继续用户的完整目标，优先推进完整傀影主题；不重复游玩旧关、不恢复剿灭v35。本阶段是现代主题入口状态与偏好功能，不是可完整游玩的肉鸽。

## 当前源码

新增 `rlv2_accounts`（账号/数据指纹/策略/置顶）和 `rlv2_topics`（每账号每主题的有界outer对象），与旧RoguelikeRun脚手架分离。源码schema升至0018_rogue_topic_state；独立QA61表，产品原存档未迁移。0017迁移只加新表，既有行保持；注入第二张表创建失败后，表及版本事务回滚通过。

现代主题表存在时，账号创建和Runtime启动初始化主题状态，同步加入rlv2。outer使用冻结PlayerRoguelikeV2声明的9个分段及已定位嵌套字段；初始余额/历史/收藏均为零或空，不自动解锁模式、分队、藏品、挑战或发奖。这是明确的本地初始策略，官方初始解锁规则尚未重建，不能称官服新号等价。

置顶接口为 `/rlv2/setPinned`，请求id接受主题字符串、null或空串（后两者清除）。只有已开始且确实存在的主题能被置顶；不赋予玩法解锁。复用账号会话、事务、幂等回执和差量组装，读取/重复请求不凭空写入进度。其他开局/游戏接口仍为明确501。

启动及备份恢复都在迁移/替换活动存档之前校验版本绑定、主题集合、保存字段和类型。不自动把缺失的余额字段补零，不因删掉现代表而隐藏既有主题状态；尚未接纳的非空任务槽/历史记录/节点升级/种子活动内容直接拒绝，而非传任意字典或静默清空。主题对象限制2MiB。

增加冻结 `cn-android-2.7.71-rogue-qa`，只接受新19表e915675d8d8a1cc97df8fa46eed27ef1bdaa9d1b0fdb07461dcabda36271ae29，协议复用已冻结display适配。独立QA配置拒绝自动重绑旧账号；没有改产品settings或发行物。

## 原生研究依据与限制

REA/Ghidra使用冻结本地ELF/metadata和完全线性解码的方法页：

- EntryViewModel.CheckIfTopicAccessible，M133330/0x3923558，312字节，ev_d0affebaffc2b6c5de3ba34f37cd0d7979a885c0b958d8b120aad874fee3da3e；消费入口模型中的可访问字段，不能只靠表上存在就推断全部玩法可选。
- RoguelikeDataUtil.IsInInitialState，M33624/0x44f140c，192字节，ev_bba304d092098cc0414fb2bbdcac93135cc6caf09c9bd9270bcb24b31f4c3f8b；默认路径读取rlv2.current.player.state并与1比较，和metadata INIT候选值对应。
- EntryViewModel.LoadData，M133329/0x39220fc，1628字节，ev_7f25860bbcf0f0f5f8086d90e78094b3c71bee119ba5e0c6df8076a4a3370411；默认路径在构造主题列表之前要求current引用非空，再允许game为空。因此无探索时输出有7个空成员的current对象，不能简单输出current:null。outer按主题TryGet，读取已有记录和置顶。

Ghidra对热修复分支报告bad instruction/全局引用警告，仍保留；只把有效默认路径用于上述判断，没有声称热修复分支或所有函数完整还原。EnsurePlayerRoguelike静态184字节未解码，未启动提供器假称完成。metadata原始压缩枚举存于本地enums-raw，仅INIT=1有上述消费佐证，其余值仍需具体消费/原生校验。

还核对了固定提交的[OpenDoctoratePy入口实现](https://github.com/jiellll1219/OpenDoctoratePy-EX-Public/blob/fcce42d48b8c4ead3aeb3f9628db91d3009f5db7/server/rlv2.py)。该第三方实现将月度/挑战改为普通模式，并给出巨大初始属性，不能证明官方规则；未照搬这些行为。另两个固定路径实际文件为零字节，未作为有效协议/规则依据。第三方文件只留.cache，不入项目源码和备份。

## 验证

17项最终主题状态专项通过，2.71秒；此前71项关联检查（当时15项状态专项加备份/剿灭持久化/周迁移范围）通过，10.93秒。两组重叠，不相加为88项；新增冻结QA门槛之后补跑了最终17项及真实数据恢复。Ruff零诊断，一项既有FastAPI/httpx弃用警告；未重跑未受影响的历史1194完整集。

在新D盘目录 `.cache/rogue-topic-20261022/state-runtime-v1/data` 复制已接纳19表，创建两份新本地账号（不是旧存档副本，未带任何官方认证）。实际验证：6主题同步、置顶/重复置顶/清除/再置顶4次POST均200、账号隔离、备份恢复后完整sync相等、关闭及重新打开Runtime后完整sync相等。61表/0018、2账号/12主题行；SQLite integrity=ok、FK错误0、探索和战斗会话均0。第一次完整sync单样本32.64ms，仅用于定位开销，不是P95基准或原生性能验收。

产品DB、settings和既有开发EXE的摘要保持。没有启动模拟器、浏览器管理面板、官方认证、真实游戏探索或新的发行构建。

首轮新检查的两个失败保留：未给seqnum时先被现有幂等键校验拒绝400，测试却期待401；使用不在白名单内的备份前缀rogue。只修正测试为带seqnum检查缺认证、使用manual前缀，未放松产品校验。两次Ruff导入顺序问题已修正，没有忽略诊断。

## 尚未完成和下一步

现代主题置顶与状态已有源码/自动/实际冻结数据的持久化证据，原生界面未验。初始收藏/模式解锁、开局及分队/支援选择、地图生成与节点、招募、战斗与奖励、主题结束和完整重启原生验收尚未完成。不要用零余额outer或成功置顶代替完整玩法。

下一步继续真实ModeViewModel的模式/分队解锁消费、pending事件字段与创建探索流程，使用已接纳的精确初始化配置；按独立Run/事件/招募实体和事务接通完整傀影主题。代表场景通过后扩展同类数据，不重复刷关；其他主题/指定玩法/完整寻访/Golden/离线/两小时/性能/HarmonyOS/成熟EXE目标保留。

证据统一在 `.cache/rogue-topic-20261022/` 的rea-state、enums-raw、state-validation、state-runtime-verification及reference/sources.json；这些官方/第三方原件与存档不入Git。新检查点索引登记 `.cache/github-checkpoints/rogue-state-20261022/`，实际远程完成以回读/新D恢复证据为准，不预填。
