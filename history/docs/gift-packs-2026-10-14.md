# 组合包与月卡：真实 501 和局部原生合同

2026-10-14。完整目标仍包含全部主要系统、指定战斗与高级模式、原生视觉和成熟版本验收。本轮研究不代表组合包业务已实现或全游戏逆向完成。

## 实际玩家表现

在独立 `cash-third-oct14-v1` 副本完成第三档首购动画后，回主页余额为107；保留此前另一副本的929存档。采购中心推荐页正常显示月卡原版图形、¥30、购买后6源石、30天每日200合成玉和一盒应急理智加强剂的文字。这些画面文字不是月卡已经入账、领取或续期的证据。

点击顶栏“组合包”，实际客户端发送 **POST /shop/getGPGoodList**，正文结构为 `{}`。路由未实现，返回501，原生显示“与神经网络连接丢失”提示。未执行任何组合包、月卡或真实支付；已有订单不因这次失败变化。原版断线画面、脱敏正文结构及请求记录留在本地忽略缓存，不用空列表或万能成功掩盖缺口。

Cash新EXE范围通过与整个采购中心失败分别登记；源石补领和动画结果见 [实际验收](cash-recovery-2026-10-14.md)。实际服务停止后数据库/外键、153保护输入和1,079发行文件均保持。

## 冻结依据

沿用官服Android 2.7.71/190、资源26-09-22-07-47-20_6c71fa、API V070，SDK v3只改变本地支付适配，原生ELF保持原指纹。冻结声明索引SHA-256为 `30c555d4479d4a0f708b9fc61aa4ecfeb945a169e4a82586e31d243afdaa4804`。REA工作流复用既有索引，补读已验证独立客户端首个file-backed代码段的五个范围，共56KiB；未读取玩家堆、匿名内存或认证数据。14个方法包络共8,328字节完整反汇编，但静态默认分支、泛型绑定与实际HTTP是不同证据；XLua覆写、全部调用者和全部支付分支未完成。

局部范围覆盖月卡详情/面板点击、GP入口和填充、月份展示、购买分派、购买前检查、普通GP请求与现金购买。完整依据留在 `.cache/rea-2026-10-14/pack-contract`：declarations、resolved-contract、functions、functions-guards、supply-evidence、monthly-limits和有界页收据。原始官方代码页与资源不随源码上传。

## 目录和请求结构

`GetGPGoodListResponse` 继承玩家增量响应，包含weeklyGroup、monthlyGroup、monthlySub、levelGP、oneTimeGP、chooseGroup、condtionTriggerGroup、conditionChooseGroup。`condtionTriggerGroup`的拼写来自冻结声明，不能自行纠正后假设客户端会读取另一个字段。

`MonthlySubItem` **继承 NormalGPItem**，不能只返回其四个新增字段cardId、dailyBonus、imgId、backId。继承项还含goodId、giftPackageId、priority、displayName、currencyUnit、availCount、buyCount、price、originPrice、discount、items、specialItemInfos、startDateTime、endDateTime、tab、gpTicketIdList、imgDisplayDataList。字段声明不直接证明所有JSON别名与当前供给，需继续核对属性及实际消费者。

周/月组具有groupId、起止时间和packages字典；普通、等级和周期套餐共享主要价格/奖励字段。玩家giftShop具有oneTime、level、weekly、monthly、choose和conditionChoose子状态，每项含info与valid；完整同步中的真实别名和限购/解锁语义仍须逐项绑定，不用SDK商品数代替这些状态。

普通 `BuyGPGoodRequest` 字段为goodId、enterTs；原生 `_BuyGPItem` 从当前商品复制goodId，并以事件记录器的enterTs覆盖初始-1，随后发送请求。返回继承玩家增量并有items。用券分支另有goodId、ticketId，不能把它与普通购买混用。`BuyHandler`区分价格类型：现金路径调用 `_BuyItemWithCash`，继而 `ShopCashPurchaseUtil.StartPurchase`；普通GP路径使用上述GS购买请求。尚未实际下单或验证这些GP履约分支。

## 月卡显示与限制

冻结SDK文档SHA-256 `443d41ce04d77899fefee78c5b6af33629db8d28d89dc0b47829491b7b60986d`中，`GP_mCard_1`对应store_id **52**、名称“月卡”、价格 **3000分**，国服官服Android且状态为1；与推荐页¥30一致。另一个“新人月卡组合包”是独立商品，不能按同一月卡SKU履约。451个SDK产品标识能匹配普通GP展示表，不证明当前商品正在GS出售，也不能推出奖励/限购。传统SKU `GP_mCard_1`没有普通shopGPDataDict项，表内另有shopMonthlySubGoodId；不能把该普通字典缺项当成月卡不存在。

原生月卡填充读取 `PlayerStatus.monthlySubscriptionEndTime(+0xc8)` 与 startTime(+0xd0)；玩家模型另有monthlySub字典，`PlayerMonthlySubPer`包含两个long时间戳。当前本地sync仍把传统月卡状态时间固定为0，订阅购买、每日奖励和期限持久化尚未实现。

`CheckIfMonthlySubPurchasable`默认分支对剩余秒数做严格比较：

```text
(subscriptionEnd - currentTime).TotalSeconds < limitDays * 86400
```

`GetMonthlySubMaxRemainDays`从常量表+0xc8读取 `GameDataConsts.monthlySubRemainTimeLimitDays`。匹配的gamedata_const SHA-256 `7a095a77b722c877bdd29ef78b314177bbd5b638cde94f7e9c24515c7b9c70ae`给出 **60**，warningTime为345600秒。60天是已确认的**购买前剩余时间阈值**，不是已证明的“续期后最多60天”；边界等于60天不通过此默认检查。实际延长起点、到账/每日领取时刻、每日物品到期和时间回退政策仍待进一步证据。不能凭常见印象硬编码其他阈值，也不能从一张30天宣传图推出所有服务端时间规则。

## 实施和验收待办

继续绑定JSON属性、价格枚举、日期和各类解锁/购买状态；导入匹配的版本目录及保留周期历史。目录缺失与不支持的选项应明确失败，不能伪造成功。实现普通/用券/本地现金履约、月卡持久化和每日领取、等级/周期/自选/条件套餐，并保持现有Cash订单与首购存档。新功能需要事务、并发/重复、账号隔离、回滚、重启/备份以及实际原生列表/详情/购买/领取/跨日验收。

保留的历史参考shop.json早于冻结资源版本，不能整包当作当前官服目录。本轮未修改业务代码，876项源码检查与Ruff结果只属于此前业务版本，不支持“组合包已通过”的结论。所有其他商店、集成战略、卫戍协议、剿灭、危机合约等模式和完整Golden/离线/两小时/HarmonyOS要求继续未完成。
