# 服装奖励、衣柜与普通服装购买

本轮补齐外观所有权、干员换装、助理外观和普通源石服装购买的领域与协议路径。销售供给来自显式导入的版本绑定目录；没有目录时返回 `SKIN_CATALOG_NOT_READY/503`。历史参考不能证明当前官服价格或周期，本轮原生验收采用明确标记的自定义测试供给。主要商店和高级模式仍未完成。

## 已确认的依据与边界

冻结客户端为国服官服 Android 2.7.71/190、资源 `26-09-22-07-47-20_6c71fa`，GameData 为 `f44199a7d34a82bdbb232674db3a3cdf9d7958230217fce3960ccafd351b7406`。只读索引 SHA-256 为 `30c555d4479d4a0f708b9fc61aa4ecfeb945a169e4a82586e31d243afdaa4804`。未修改冻结表、原 APK 或既有发行目录。

| 路径或字段 | 本次依据 | 实施范围 |
|---|---|---|
| `CHAR_SKIN` | 冻结 skin_table 的 skinId/charId/tmplId 与默认映射 | 写入 OwnedSkin，不进入可堆叠库存；允许先拥有服装后获得角色 |
| `/charBuild/changeCharSkin`、`/user/changeSecretary` | 两个冻结请求均声明 charInstId:int、skinId:string；响应为 PlayerDeltaResponse | 账号、所属角色、持有及精英阶段检查；单位与助理外观独立 |
| `/shop/getSkinGoodList` | 衣柜实际请求曾返回 501；默认 native `0x41869a4/0x41d36a4` 均构造 charIdList:[] | 从目录返回 ordinary goodList；null/非空筛选属于兼容设计，未证官服服务端行为 |
| `/shop/buySkinGood` | 请求 goodId/isSpecial/enterTs；默认 native `0x41cb978` | 一次购买一套，服务器决定价格、有效期和权限；isSpecial 接受严格 bool 或 0/1，enterTs 允许 -1，不能授权购买 |
| isSpecial | 来自 spDynIllustState | 特殊动态立绘购买明确 501；不能把它解释为兑换券开关 |
| SKIN | 构造函数 `0x401b6f0/0x401b7b0` | `{info:[],gachaGood:{info:[]}}`，购买后计数与持有状态一同同步 |
| characterSkins / skinTs | PlayerSkins 字段及 `0x43f1774` 消费链 | 前者保存拥有标记 1，后者单独发送首次获得时间，重复奖励不刷新时间 |
| skinSp | 声明为 ListDict<string,bool>，PlayerSkins 构造函数 `0x401c1d8` | 普通服装使用空集合，不发放特殊立绘权限；bool 泛型构造内部未完整还原 |

新的只读核对包含 36 个 native 范围、31 个完整线性解码范围；获得时间问题另核对 6 段、2,356 字节。它们只证明相关原始默认路径，不能代表动态 Lua 分支或完整原游戏逆向。证据保留在 `.cache/rea-2026-10-13/skin-shop-contract/` 与其 `ownership-time/` 子目录。

冻结表有 2,386 个外观条目、520 套独立服装。活动获得的外观也可能标记 isBuySkin=true，此字段不能用来推断现金或源石价格。升变模板可能不在 character_table，所属关系必须由冻结 patch 映射和匹配的默认外观核对；不能按皮肤 ID 前缀猜角色。默认、精英化及转职默认外观不能作为服装奖励绕过解锁。

## 目录与交易

`skin_shop.json` 必须显式包含 schema_version、gamedata_hash、client_profile、catalog_id、mode、provenance、blindbox_supply 和 offers。mode 为 custom 或 frozen-observation，后者仍需外部观察证据，格式通过不会自动证明官服真实性。blindbox_supply 当前只接受 closed。

普通商品字段为 goodId、skinId、price、originPrice、discount、slotId、startDateTime、endDateTime。只支持既有 4002/DIAMOND 钱包；名字与角色归属取匹配的 skin_table。商品、外观和排序标识不能重复；默认外观、未核对的特殊立绘、无效引用、错误版本和异常 JSON 在打开存档前拒绝。

销售时间采用服务器时间，结束时刻不再购买。-1 是显式无限期配置，不能把过期历史商品自动改为永久供给。客户端会对已拥有的永久商品结合 skinTs 与 UnlimitSkinOutOfTime 判断展示；不能把获得时间塞进 characterSkins。

一次事务提交源石扣款、OwnedSkin、SKIN 永久计数、PurchaseHistory、增量和幂等收据。重复同请求返回原收据；不同请求购买已拥有服装返回 409，不再扣款。奖励失败会回滚所有写入。时钟回拨不会重置持有或购买记录；配置换代保留旧目录字节和新目录的内容指纹快照。

现有 EXE/命令入口新增：

```powershell
TerraLocal.exe --data-dir D:\TerraLocal\data skinshop import D:\TerraLocal\offers.json --dry-run
TerraLocal.exe --data-dir D:\TerraLocal\data skinshop import D:\TerraLocal\offers.json
TerraLocal.exe --data-dir D:\TerraLocal\data skinshop show
```

这些命令仅处理本地目录，无网络认证。成功 stdout 是 JSON，包含目录范围、mode、client_profile、gamedata_hash、catalog_hash；import 另含 dry_run、snapshot、restart_required。格式/引用错误写入 stderr，退出码 2；成功为 0。导入不修改数据库，也不热改运行中的供给；重启后启用。doctor 增加 skin_shop 概要，完整 ready_for_play 仍为 false。

## 实际验证记录

服装代码完整 **761 项通过（111.84 秒）**，Ruff 零诊断；覆盖目录、首次获得时间、整数布尔编码、账号隔离、购买事务、并发、重试、失败回滚、时钟和目录导入/存档恢复。较早目录阶段为 752 项通过（119.65 秒）；补齐 skinTs 后为 757 项通过（109.27 秒）及外观专项 87 项通过（21.19 秒），保留为阶段记录。

前次源码原生测试已真实登录并进入干员页面，打开衣柜收到一次 `/shop/getSkinGoodList/501`。该失败记录及截图保留；24 张跟踪表和 124 份输入保持。随后的一次测试在核对 skinTs 缺口后停止，未购买或完成外观验收，不计为通过。第一份新 EXE 实际打开衣柜、预览并穿戴阿米娅报童，单位与助理保持独立；确认购买陈岁红霞时，客户端 isSpecial 为 int，被旧严格 bool 校验以 422 拒绝，钱包 60、持有和购买记录均保持。已限定兼容 0/1 编码并新增四项回归；该失败的截图、旧程序和测试库保留。普通 bool/int 标志等价回放专项 33 项通过（16.14 秒）。

修正后的独立 EXE `20261012T235828.642143Z-a5304dab`，SHA-256 `fc0a46c8400a31d82d677c336c57e8008723df728c9eb7ff9c80253d7311880a`，1,079 文件指纹核对通过。真实原生衣柜确认购买陈“岁红霞”：源石 60→42，新增一条购买、一个永久计数和一套持有；原版获得动画、获得卡片及穿戴均正常。陈与阿米娅报童分别通过 `/charBuild/changeCharSkin/200`，单位外观保持独立。自定义测试目录只有一套商品，价格和测试周期不代表当前官服供给。

该运行的最终脚本在要求助理已经切换的断言失败；此前扣款、持有、计数和两套穿戴断言均通过。不能将脚本整体标为成功，购买部分单独保留证据。重新启动同一 EXE 和客户端后，源石 42、两个原版角色头像和陈立绘均正确；25 张玩法表一致、128 份保护输入保持、数据库完整性通过。接续结果在 `.cache/home-rotation-2026-10-13/resume-results.json`，截图保存在同目录，旧程序和旧测试库未替换。

新增 A15：新版助理编辑页缺少真实 `charRotation.current/preset`，进入页面时抛出 `HomeSecretaryChangeStateBean.get_displaySkin` 空引用，没有发送旧 `/user/changeSecretary` 请求。该问题须补齐轮换预设与新请求，不能靠只写旧秘书字段或空字典解决；见 [看板轮换记录](home-rotation-2026-10-13.md)。

## 未完成范围

当前官服服装销售目录、兑换券、现金服装、特殊动态立绘、盲盒、升变模板解锁、头像附赠规则仍未验收。普通目录中的 closed 只说明所选供给关闭盲盒，不说明官服当前活动。

Low/High/Classic 等其他商店目录、分组阈值、阶梯终点及周期仍有缺口；肉鸽、卫戍协议、剿灭、危机合约等完整玩法，以及全系统视觉、Golden Playthrough、完整断网、两小时和 HarmonyOS 验收保持未完成。本轮不得据服装路径通过宣称成熟发行或全部 bug 已解决。
