# 协议验证

历史路由候选：`/account/login`、`/account/syncData`、`/account/syncStatus`、
`/quest/squadFormation`、`/quest/changeSquadName`、`/quest/battleStart`、`/quest/battleFinish`、
`/quest/saveBattleReplay`、`/quest/getBattleReplay`、`/config/prod/official/network_config`。

路由存在于上游代码不等于当前客户端验证通过。每个 fixture 标注来源、版本、请求/响应 schema、
语义、验证等级（synthetic / reference / client）和脱敏规则。未知端点返回明确 NOT_IMPLEMENTED 并记录
结构，不以空 JSON 返回成功。日志不记录 password、token、cookie、secret 或真实账号标识。

delta 的 modified/deleted 必须使客户端镜像与同一提交后的完整 syncData 一致。
战斗报文先验证解码和 session 关联，再提交奖励；不能伪造服务端完整战斗演算。

## 当前 2.7.71 证据

| 端点/字段 | 请求及认证 | 响应/业务 | 验证等级 |
|---|---|---|---|
| SDK 更新、U8、account/login、syncData | 静态 Java 更新回调和本地分阶段凭据 | 本地版本、会话和 8 个实体分支 | client：已登录并显示主页 |
| agreement_version / update_agreement | code 实际为 U8 令牌；不能使用 SDK 或游戏令牌 | TerraLocal 说明 URL 和账号接受记录 | client：WebView 和接受通过 |
| pay/getUnconfirmedOrderIdList | 空对象、游戏会话 | 账号 READY 本地订单 ID 队列和空增量 | client：读取通过；创建/履约未实现 |
| charBuild/batchSetCharVoiceLan | voiceLan 字符串、游戏会话及 seqnum | 语言校验、合法角色回退、持久化 delta | client：批量中文通过 |
| charBuild/setCharVoiceLan | voiceLan、charList 实例 ID 列表 | 只修改拥有的角色，开放时间校验 | reference/synthetic：UI 待验证 |
| account/syncStatus | modules 实际为 3807；params.16.goodIdMap | 命名模块结果和账号 delta；未支持已有状态明确拒绝 | client request；响应仍待通过 |
| story/finishStory | storyId、游戏会话和 seqnum | 匹配剧情条件、一次性奖励、单调进度、完成记录 | client request；领域测试通过，提交待验收 |
| shop.HS.progressInfo | 完整 syncData 分支 | Dictionary<string, PlayerGoodProgressData>；空值为对象 | client：数组造成反序列化失败，修正后可加载主页 |

冻结 metadata SHA-256 为 `bf14421bbafe9c71d944ba4f97b31ecd666232640eac0829db3d84ac716ac8b8`。
只读工具 inspect_client_metadata.py 固定校验此指纹，输出选定类型/字段和压缩整数枚举，
不注入进程、不读取会话、不调用官方服务。结构及压缩整数参考
[Il2CppDumper 的结构定义](https://github.com/Perfare/Il2CppDumper/blob/master/Il2CppDumper/Il2Cpp/MetadataClass.cs) 和
[整数读取实现](https://github.com/Perfare/Il2CppDumper/blob/master/Il2CppDumper/Extensions/BinaryReaderExtensions.cs)。

| PlayerSyncModuleMask | 数值 | 当前边界 |
|---|---|---|
| UNREAD_MAILS / FRIEND_REQ / ANNOUNCE_VER / REFRESH_USER_CARD | 1 / 2 / 4 / 8 | 邮件提示、空申请、本地公告版本和账号字段 |
| GOOD_PURCHASE_STATE / CASH_PURCHASE_STATE | 16 / 32 | 购买计数；被查询的已有购买状态尚未支持 |
| CLUE_STATE / SYNC_BUILDING | 64 / 128 | 线索提示；仅未初始化基建，无生产结算 |
| SYNC_CRISIS | 256 | 明确未支持 |
| SYNC_ACTIVITY / SYNC_MEDAL / CHECK_FORBIDDEN | 512 / 1024 / 2048 | 空活动/章状态、本地功能限制；已有活动/章结算未支持 |
| SYNC_ACTIVITY_FIXED_INTERVAL | 4096 | 与活动刷新相同边界 |

PlayerStageState 确认为 UNLOCKED=0、PLAYED=1、PASS=2、COMPLETE=3。
这与领域星级分别表示，不使用“unlocked=true 就输出 1”的旧推测。
PlayerSyncAnnounceVersionResult 有 announcementPopUpVersion/announcementVersion，
PlayerSyncGoodPurchaseResult 有 goodPurchaseState，PlayerCheckForbiddenResult 有 gacha/shop ID 列表。
上述字段存在不代表所有非空值语义已明确，缺口继续单独记录。
