# 傀影首次通关藏品通知与奖励

遵照用户不重打同关、停止剿灭、代表通过后批量接同类接口的安排。本阶段0新原生战斗；合成HTTP日志只验证服务事务，不称真实Boss胜利。完整交付仍未完成。

## 规则与来源

- 业务指纹822370e327a3de7fd8e7080f89ead6474f5b4556ec7968e47f5980e56ebe21d9，schema0033/74表，19表版本e915675d8d8a1cc97df8fa46eed27ef1bdaa9d1b0fdb07461dcabda36271ae29。
- 承接[20项资格及REA消费者](roguelike-ending-unlocks-2026-10-28.md)：M136006/136047默认分支读取outer.relicUnlock的ID顺序、逐项表lookup/render和数量；relicBp提供额外蜡烛显示。不是官方服务端解锁判定。
- [PRTS傀影与猩红孤钻](https://prts.wiki/w/傀影与猩红孤钻)的本主题检索正文摘要明确新解锁收藏品每件额外25蜡烛并受当期上限限制；这是有限、明确版本的社区玩家规则适配。全局relicTokenRatio=10没有本主题服务端消费者证明，不能混用；旧刻俄柏10蜜饼不推广至此。
- 策略rogue1-normal0-completion-unlocks-prts25-v7只包裹当前已接通的NORMAL0各类自然结束。20项c01..12、m10/11/12/16/17/18、n01/02用完整验证的本账号SETTLED历史计算资格差集；pending/失败/EASY不产生新完成资格。不是全部37种结束条件，也不是自然地图供给。

## 实现

每行保存sequence、前一结算run/hash、底层评分策略及奖励规则指纹。旧v1..v6继续按原次序和原计算验证；不重写旧hash/响应/收据，不追发升级前已符合资格的奖励。新行使用明确历史顺序，避免同秒UUID顺序改变通知。关联长度有界，每行不复制全历史；验证仍重算前缀资格，不能称全部历史处理为常数时间。

game.score.bp/gp保留基础评分；outer.relicUnlock给新资格ID，outer.relicBp给基础评分之后的额外数值，outer.gp给额外灵感。每件25蜡烛受实际开放窗口BP上限限制，不扣已有超限BP；灵感按累计蜡烛跨十进位且受grow上限限制。不授实际局内物品或state2/效果。结束行、外部余额、run关闭在同一事务提交；新序号重试可创建传输收据，业务奖励不重复。

当前图鉴和分队次数复用同一完整结束历史校验；预检同样核对顺序、余额衔接、事实、规则hash、响应、归属和原始战斗/地图/场景/商店记录。

## 自动与正式表验证

- notification-base-v1.xml原75通过；rewards-pure-v1.xml的27通过；reward-related-v1.xml的122通过（普通/商店/最终Boss结束、图鉴、新奖励）。与32项未改的纯完成规则检查去重后，本阶段当前154项不同检查通过；6个变更Python文件Ruff通过。不因数量宣称全游戏无bug。
- 新合同覆盖实际+500/额外50灵感、上限/进位、双Runtime并发只发一次、事务中途故障回滚、同/新序号重试、第二次成功不重复发奖、首行响应永久不漂移、普通败北也使用同一有序策略、篡改7类字段拒绝且启动不改坏库、Runtime/BackupService恢复。
- rewards-frozen-verification.json：正式19表旧17完整用户与16d2逐字段相同、旧74表原始行不变、旧响应不追发；新D原pending成功17仅确认一次，437基础+500额外=937蜡烛、43+50=93灵感。全部旧16完整用户/永久库存不变，6表发生预期变化，其他68表保持；Runtime/BackupService/新D完整17用户及74表相等，162保护输入保持。没有重新战斗。

## 保留的失败与修正

reward-http-v1.xml保留2失败/1fixture错误：重试新seq预期所有原始表不变忽略了新传输收据/revision；第二次结束预期137灵感忽略fixture实际grow上限100；普通结束fixture插入20资格却缺完整ending目录，严格503。修正检查前置与预期，没有为过检查放松业务校验。原7篡改检查已过；v2补验3项通过，最终相关122全过。

冻结验证v1在全部delta/奖励/重试/旧库对照通过后，误期望普通游戏结算新增GM audit_records而失败；实际只6表变化。v2保留现场继续备份/恢复核对，不再次确认或重放战斗。原始脚本/失败输出仅本地保存。

## 原生与余项

新的20项通知页、额外蜡烛/灵感合计展示已通过一次原生代表。源码cee51be/业务822370e3，独立D副本只消费原有pending成功，所有开战/招募/其他rlv2入口被QA守卫禁止；没有重打Boss、主线或剿灭。

- `.cache/rogue-unlock-notice-native-20261028-v1`：42HTTP全部200，rlv2仅1次gameSettle，0新招募/战斗。screen15基础437分/+437蜡烛、16基础+43灵感；17显示“本次探索新解锁20个收藏品”及真实图标/名称/条件、额外+500蜡烛；19显示额外+50灵感/LV4(137/200)；20回到主页，幕后筹备93/开始探索。只看一个列表代表，没有逐件重玩。
- 无Lua nil/异常类型；59其他账号表投影、旧16完整用户及163保护输入保持。最终rlv2与自动正式表新奖励结果逐字段一致；Runtime/BackupService/新D全部17完整用户及74表相等。50319实际exit0，PID3960实查缺席、18443监听关闭，自有ADB/index1正常停止，index0保持。
- 初次使用短commit“cee51be”被完整SHA守卫拒绝，启动前exit1；改传完整SHA后开始唯一原生会话。seq5误用x/y而非xy，KeyError发生在Android输入前；重新截图审阅后正确xy输入成功，失败ACK保留。不是重复点击或重复战斗。
- SDK弹窗虽然使用原生固定标题，实际路由`protocol/sdk.py`提供的是TerraLocal本地存档说明；本次只记录本地账号说明版本，不接受官方绑定/认证或支付。合成前置保留6导航guide/progress100，不能称真实Boss通关；零时长fixture的历时空白限制继续保留。尚无本轮新EXE。

其他17种结束附加条件、隐藏路线物品自然获得、自然地图/供给、其他主题和完整交付仍待完成；既有资格与新结算实现不替代这些范围。

## 完整私有检查点

源码3696eb1930e4909ae1fa2619a2ebc98e9e24cf9c/业务822370e3包含上述实现、失败与原生/恢复记录；上传[613e0ca固定索引](https://github.com/hanshuqimen/TerraLocal/blob/613e0cab52e8ea35b0968e320a9ecd331981881b/README.md)。完整bundle1913853字节，SHA256 `53ba18e3ce03bf54eb7e0e806dba61929cdf8284012a3c5900a91162a5378841`，Git blob `aa25f56b323dee081adcb37ce9e063e142c4e296`。459文件/163提交及全部461历史路径/1929blob扫描，禁止内容/凭据标志命中0；旧175非README项及原README全文保持。

已实际浏览器下载，双hash与远程固定索引回读通过，`.cache/github-checkpoints/rogue-unlock-settlement-20261028/restored-remote-3696eb1`中新D全部源码/历史/Prompt/fsck/干净检出相同。权威upload-verification.json和heartbeat-latest.json；仅把本次新C下载移至D，保留所有旧备份。授权完整bundle备用方式，不冒称普通源分支push；本完成段晚于已上传源包，不为补这段重复打包。
