# 普通战斗开始与主动放弃验收

2026-10-09。只使用 LDPlayer index 1 / <test-transport> / <test-device>、独立本地 Doctor 存档。
游戏外网限制保持启用；源服务器监听 18443。正式存档仍为 0004，已有 Windows 程序尚未包含本轮实现。

结论：冻结客户端的 0-1 普通战斗开始、主动放弃、退款、返回地图及服务器与客户端重启已通过。
正常通关、首通奖励、代理保存、其他战斗模式没有完成真实客户端验收，不能标记完整战斗闭环。

## 客户端契约与依据

冻结 CN Android 2.7.71 / 190，GameData 指纹
`f44199a7d34a82bdbb232674db3a3cdf9d7958230217fce3960ccafd351b7406`。
类型来源为 `.cache/client-metadata/official-index.sqlite3`；有界原生代码读取仅针对已验证的文件映射。

- `/quest/battleStart`：普通请求包含 stageId、完整 squad、usePracticeTicket、assistFriend、isReplay、
  startTs、isRetro、pry、battleType、multiple、extra。Common / Continuous / MULTIPLE 分别为 0 / 1 / 2。
- `/quest/battleFinish`：CommonFinishBattleRequest 声明 data 与 battleData；DefaultFinishBattleRequest
  没有额外声明字段。外层 BattleDataInRequest.stats 是字符串字典，实际主动放弃请求为空字典。
- 解码后 battleData.stats 为 BattleLogger.BattleStats 的嵌套对象，不能把它当成外层字符串字典。
- CommonFinishBattleResponse 继承 PlayerDeltaResponse，并定义奖励列表和 apFailReturn；
  DefaultFinishBattleResponse 增加倍率、首通奖励、解锁关卡、提示和可选 extra。
- PlayerBattleRank 为 FAIL=1、PASS=2、COMPLETE=3。只有 FAIL 已取得本轮真实请求；PASS / COMPLETE
  的领域结算目前由合成数据检查，未据此宣称真实通关通过。

开始请求普通原生分支切片 SHA-256：
`a5dbbfa6823a324f73ca0cc1eca484b894185bb50561c3e32922ecf3e0050e42`。
签名及结果组合切片 SHA-256：
`374607b9e88361f8e699ae515e8dd309e87b58ca3e0c20937f4d6b73c3292ec8`。
完整日志格式切片 SHA-256：
`7f564768cb98b30db8bf6fefb6f5c513dca87da7e882921fdaf012c82a0e78c9`。

## 实际结果编码

普通原生代码确认：UTF-8 battleId 的每字节加 7 后 Base64 得到 isCheat；
结果 JSON 使用 CBC、PKCS7 和随机 16 字节 IV，data 为密文十六进制接 IV 十六进制。
候选密钥公式来自历史协议线索，已成功解码本地真实请求：

```text
key = MD5(UTF8("pM6Umv*^hVQuB6t&" + str(login_time)))
data = hex(AES-CBC-PKCS7(JSON, key, iv)) + hex(iv)
```

没有宣称从冻结客户端元数据中找到了该前缀，也没有读取玩家 logToken 或匿名内存。
此编码不能代替账号认证：服务器先验证本地游戏会话和战斗归属，再解码与核对关卡、签名、时长。
解码后的访问、包名、散列及反作弊日志字段不写入业务存档、收据或日志，也不设置服务器时间。

真实主动放弃的结果为 interrupt=1、giveUp=0、completeState=1；不能只检查 giveUp 判定放弃。
解码后的根字段有 battleId、stageId、completeState、interrupt、giveUp、percent、killCnt、
validKillCnt、platform 与 battleData。额外模式及未知根字段明确拒绝。

## 事务与存档

- 普通 MAIN / NORMAL / NONE 的手动作战，编队必须与已保存的编队一致；不忽略模组或额外模式。
- AP 扣除、BattleSession、开始次数和请求收据在同一事务中保存；开始时间来自服务器。
- 迁移 0007 增加 nullable native_context，记录编码版本、GameData、登录时间和掉落规则指纹。
  旧战斗保留 null，拒绝把未经验证的旧会话伪装成已绑定的游戏端战斗。
- 结算按领域结果保存散列；不同序号或不同随机 IV 的同一结果不再发奖/退款，冲突结果返回 409。
- 结算、AP 退款、进度、上下文、增量和收据共同提交；响应组装失败全部回滚。
- 只尝试开始时与当前登录标记两个有依据的密钥时间，不遍历时间。多次并行登录与途中换设备尚未验收。
- 战斗期间 GameData 改变明确拒绝；成功结算还要求开始时与当前掉落规则指纹一致。
  主动放弃不依赖掉落规则。缺少规则的成功提交返回 DROP_RULE_MISSING，保留未结算状态。

## 真实客户端操作

早先两次战斗提交为 501，分别是无部署漏怪和主动放弃试验；没有标记通关。
它们的数据库与请求已保存，后续经本地技术清理退回 AP；这两次清理不能计作原生客户端结算成功。

第三次试验使用新版本记录与真实客户端请求：

| 步骤 | 实际结果 |
|---|---|
| 进入 0-1 并开始 | `/quest/battleStart` 200，240.48 ms；AP 123 → 117 |
| 主动放弃 | 客户端提示全返还 6；实际结果 rank=FAIL、interrupt=1，时长 18 秒 |
| 提交结算 | `/quest/battleFinish` 200，40.18 ms；存档为 ABORTED，AP 123 |
| 查看结果与返回 | 结果界面显示理智返还 6，随后正常返回 0-1 地图，没有断连弹窗 |
| 重启服务器后重试 | 本地 HTTP 测试工具两次提交原请求均 200，AP 保持 123；没有追加退款 |
| 冷启动客户端 | 游戏登录、syncData、syncStatus 均 200；主页 AP 123，没有数据更新失败 |

关卡仍为零星、零通关、未领取首通奖励；没有伪造成功。
冷启动样本延迟为登录 5.76 ms、syncData 32.74 ms、syncStatus 40.46 ms。
开始请求 240.48 ms 的单次样本需在性能验收时继续核对，不宣称达到完整性能指标。

私有回执：`.cache/refresh-diagnostic/recruit-oct09-v1/client-validation-native-abort.json`。
回执记录源码、请求和截图指纹；137 为退款结果，139 为地图，145 为重启主页。
验收后备份 `native-abort-accepted-0007.sqlite3` 完整性为 ok，无 STARTED 战斗。
加密原始请求只存放在忽略版本控制的私有诊断目录；发布检查采用合成标识和合成遥测。

## 检查与剩余范围

开始适配新增 20 项检查；结算新增 27 项，覆盖重试与并发、账号隔离、非法密文/签名/枚举、
版本与关卡冲突、旧数据库迁移、缺失或变化的掉落规则、响应失败回滚及合成通关奖励。
完整回归 236 项通过（31.62 秒），修改文件 Ruff 通过。

正式掉落数量/概率、正常通关请求、二星与三星实际显示、首通领取、解锁后续关卡、原生代理保存、
演习、助战、连续/多次作战、特殊关卡与 AP 保护仍待完成。当前 GameData 的掉落展示标记不含完整
数量与概率，不能据此声称已经还原正式掉落。Golden Playthrough 与成熟交付尚未通过。
