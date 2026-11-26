# 危机合约 V2：原生战斗路由与持久响应（2026-11-21）

在[原子通关](crisis-atomic-clears-2026-11-21.md)后，新增原版四字段开战请求及两路由 `/crisisV2/battleStart`、`/crisisV2/battleFinish`，连接已绑定的会话和通关/战败/退出事务。已通过HTTP、真实HTTPS及存档恢复检查；原版客户端画面和自然战斗尚未验收，不能据此标模式完整可玩。

## 本次 REA 与冻结依据

开战继续沿用已核 M27994。新增结算路由绑定来自既有 M162862 正常分支：字面量全局0xbff94d0→文件格0xc60e8a8→编码0xa000cf91，索引26568确为crisisV2/battleFinish；类型全局0xc061120对应FinishBattleServiceConfig<CrisisV2BattleFinishRequest,CrisisV2BattleFinishResponse>，构造MethodSpec250307的参数同样匹配。使用已核开战字面量作阳性对照，不读取堆字符串或活动Hotfix。

仅index1一次启动，按现有硬件0063090c、APK/ELF、资源、f441数据、TLS和IPv4/IPv6离线核对读取0x3120000/0x3121000两页8,192字节。每条Android命令继续8秒，文件映射/同shell硬件及进程身份检查保持，没有游戏API监听器、官方认证或玩家对象读取。index1正常关闭，index0及宿主保存保持。

9个新REA默认方法共1,980字节，组合两页已加载代码及三页冻结APK，各方法均来自单一来源；容器28,672字节，SHA-256 02dc572c5c55d8fc5f0849300cc8af184330b881588b4b4548661b006b4fe88c。public status/close成功、实际控制器/子进程退出0，输入未改。M101850经IFinishBattleServiceConfig接口分派，不能把它误认另一个硬编码路由getter；完整路由绑定取上述构造调用。Ghidra将元数据初始化器标成noreturn，尾调用布尔谓词有返回原型限制，只采用正常路径、实际指令和元数据共同支持的结论。

M162745取runeDataMap，再按实际PackedRuneData.id比较已带入的效果列表；结算列表需要实际符文ID，不是普通槽位ID。M28000金钱/经验倍率均为0，M28001/28002/28003对应首次奖励、解锁关卡及警报为null；本地结算只更新任务可领取状态，领取另行交易，不发送普通通关奖励。

## 实现与保存

四个开战字段为mapId、runeSlots、squad、assistFriend，复用已核编队模型；未支持助战明确拒绝。结算先鉴权并只做一次所属会话/版本/日志解码，再进入通关或退出事务。响应只输出已声明的九个专有字段和基础奖励渠道，不泄漏内部ClearResult、密文或遥测。

映射v1为明确本地展示策略：scoreRecord取本场结算前六轴纪录，scoreCurrent取绑定选择的分数，轴或单场纪录提高置isNewRecord；commentNew/Old分别取本场新获/本场已获评语，runeCount恰两个已完成槽位去重数量，runeIds从选择槽映射实际符文。失败/退出显示所选挑战分数作预览，不把它写成通关分数，纪录标记关闭、数量不增长。它遵循已核字段消费者，不宣称已恢复官方后端的全部业务映射；原生画面仍须核对。

首次响应存入独立、绑定battleId/开战和业务回执摘要的本地Receipt键，同一SQLite事务提交；响应失败则连同终态和进度整体回滚。旧退出/通关v1保持兼容，无新表或迁移。只读启动/恢复检查新增原生响应的类型、引用、所属账号/战斗、摘要、时间和孤儿记录。重试先检查本场业务事实，再返回首次投影；后来地图进度不会重画原答复。SHA只证明一致性，不是防恶意重写保存的认证机制。

该原生响应ts被客户端用于finishTs；Runtime新增显式preserve_result_ts选择，避免新序号重试把首次完成时间改成当前时间。默认其他调用行为保持，缺失/错误时间整体回滚。原始回放尚未归档，原生代理功能未据此开放。

## 真实数据反例和纠正

首批20项自有HTTP夹具检查通过，但夹具和实现共同误用了packedRune.key。首个冻结HTTPS结算返回明确503，通关/响应事务全部回滚，保存仍为STARTED；服务器正常退出0，失败副本保留。随后核原版字段29443为id/string/+0x10，实际导入五图共147个runeDataMap条目，其字典键/runeId/packedRune.id全部一致；148个NORMAL槽都有非空符文引用，临时图crisis_v2_01-07有两个槽引用同一符文。这是该匹配包的观察，不推广所有地图。撤回key假设并修正源码和夹具，额外覆盖错id和错key别名的拒绝，源表未改。

首个目录native-battles-https-v1及其4次请求（最后503）、待结算保存和退出0日志保留。新v2目录从原始冻结表重新建立保存，没有覆盖失败或现用存档。研究中一次误用catalog.sources被AttributeError否定，改用已有info(season)/rules接口；原输出保留。

## 已完成的检查与剩余验收

当前196个不同定向检查通过（22新原生API/174关联），覆盖五种结算分支、实际符文ID与两个数量、同步增量、鉴权/严格字段、重试/并发、后续进度保持、错误格式全事务回滚、时间选择及只读损坏/孤儿拒绝。174关联组的工具句柄在取尾输出时已失效；完整JUnit为174通过、无匹配测试进程残留，未补造进程退出码，也未为记录重跑未受影响检查。Ruff和空白检查通过，旧Starlette/httpx弃用警告保留。

v2冻结147符文/首季五图做40个真实HTTPS POST，验证TLS且全200，实际通过原生开战/结算路径及自造日志/计数的通关；三个独立HTTPS服务进程均退出0。82张表冷启和新目录恢复全行一致，首次响应及完成时间保持，源/现用/资源和数据库保护指纹保持。仅小样本延迟，不称P95或整机性能验收；没有新关卡游玩。

证据位于 `.cache/crisis-20261119/native-battles-progress-summary-v1.json`、native-finish-route-binding-v1.json、native-responder-probe-v1.json、loaded-native-route-20261121-v1/、mcp-native-route-v1/、native-battles-v1/v2/v3.xml和native-battles-https-v1/v2/。私有token/原始表、数据库/日志/代码页及REA工具均不发布。

下一补一个原版客户端新代表，核登录/信息缓存/地图/开战/结算消费，再继续任务领取、额外符文解锁、模式商店及原始回放。原生计数实际格式和110/220阈值差异仍待匹配版本证据，完整其他模式、Windows新包、断网/两小时稳定性/HarmonyOS等原始交付目标保持未完成。


## 公开源码与恢复回读

2026-11-21 原生战斗路由源码ec9f1a6已公开至main e1157d6；27发布对象Git SHA全部匹配、24新blob扫描通过，774公开文件与727源码/384完整历史实际匿名下载及项目内新目录恢复，全文件SHA-256/Git对象、严格fsck和干净工作区通过。Public/MIT实际回读，恢复后才轮换两索引，旧包/索引保持。历史增量363795字节/SHA-256 4a801c37f3b8201648a551ac7ef14ccf7dd9213d99b2f0b881fe10e7c93c780b，Git blob8fd30f3ea778b941139857243a9f9f1de286e2ce，仅需原始d40完整包。本次发布会话未发生Node重置或上传错误，不沿用上次发布失败描述。证据 .cache/crisis-20261119/public-checkpoint-ec9f1a6-v1/readback-verification.json。含196当前检查、五图40 HTTPS/三服务82表恢复、8KiB与1980字节REA及packedRune.id纠正；原版画面、领取/解锁/商店/原始回放与成熟成品仍未完成。本段回执晚于源码包。
