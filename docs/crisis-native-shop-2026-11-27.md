# 危机合约原版商店：数据与购买合同（2026-11-27）

接续已公开89e3dee/main c35475b的任务入账；本次开始HEAD8f848a0，工作区只有上轮窗口失败记录及其STATE归档，没有新的业务差异。完整服务端/成熟Windows交付目标保持。原版币代表因窗口工具黑图/激活错误尚未领取，控制器42172已实际退出0、回调和index1收尾、源/现用和旧QA保持；不能把connected当作原版消费通过。

## 版本固定的协议证据

冻结ELF3ece1e7b、metadata bf14421b及14457902二十表基线保持。metadata核验Common商品及两类子类、分档、购买请求/响应的继承、字段和偏移，九类的自定义属性实查均无字段别名。原版getGoodList空请求及permanent/season/progressGoodList响应沿用前批实际绑定。

五个购买消费者M163922/163924/163928/163971/164079共1796字节完整可解，三页REA容器SHA-256 `d864be50b6a051443ec0222ef945174d2668cbe740b6f822c7eb6628fbc47a34`。五处伪代码实际成功：主体赋值goodId/count/perm，空参数重载默认count1，回调读取items，分档按order精确查找，数量上限读取V2 shop.coin与价格。没有按类名猜URL；冻结字面量26570实际是 **`crisisV2/buyGood`**，与CrisisBuyShopRequest、MsgBundle及MethodSpec289720/SendRequest/CrisisBuyShopResponse泛型绑定，另以已原生验证confirmMissions为正控制。

请求为goodId:string、count:int、perm:int；响应items是RewardItemModel列表，其字段为type/id/charGet/count。商店保存info元素是PlayerGoodItemData的id/count，分档保存是count/order。不要把goodId与保存id混用，也不把购买字段叫法推成路由名字。

该REA89721公开close返回cleanup_incomplete（Java启动身份observed java与期待绝对路径不符），子进程0、包装器实际退出1、输入保持；未称public close成功。读取当前资源后确认报告的Linux PID496与该唯一rea-ghidra-h7VhKf目录均已不存在，没有按旧PID杀进程或删目录。该审计后才打开第二目标。

另四处M28949/163973/163975/163980共288字节的REA20156已全部成功、public close成功/实际退出0。原版PlayerGoodProgressData构造明确order=1；两个getter按seasonFlag选择对应模型，分别返回buyCount和ableBuyCount，不在getter里减库存。具体perm枚举值、库存更新/末档行为继续按原版来源核实，不按成员声明顺序推值。

M164047价格/物品显示函数的冻结体336字节起始不能解码，拒绝当作已逆向。随后仅采它所在0x4170000一页4096字节，95583实际退出0，候选完整可解；无API监听、无回调写入、无界面输入或账号交易。硬件/同shell进程、APK/资源/表/ELF、TLS与离线守卫保持，index1关闭、index0及源/现用/旧QA保持。后续从该已验单来源页做REA，不拼猜测函数体。

## 参考商品目录的实际范围

已从[固定参考版本](https://github.com/jiellll1219/OpenDoctoratePy-EX-Public/blob/fcce42d48b8c4ead3aeb3f9628db91d3009f5db7/data/shop/shop.json)只读取得1116645字节，Git blob `38bfdeb8a188751e5a7c2b0f0a5208f3719bb1c6`及SHA-256 `2f909d059b620e9e5876903bef6ed2f7a263130b284d6aba78668d21c60c03a1`完整匹配。连接器直接返回解码的原文件，首次按原始GitBlob响应结构读取失败后改查实际返回结构，没有绕过指纹或修改来源。文件和GPL参考仅本地，不执行参考服务器代码，不复制到MIT实现，不导入playerDataDelta。

该目录47永久、22赛季、4组各6档商品。所有89个实际ItemBundle引用和类型匹配冻结物品表；但这不证明目录等于目标版本官方新账号库存。永久商品跨首季至第四季，供给时间必须逐项核对；四组均从order1开始，基础progress行item=null/price0/availCount0，与正常商品不能使用同一发奖解析。

22赛季商品窗口为1755158400..1756324799，对应第四季；本地当前只导入的首季地图窗口是1700553600..1701719999。不得把这22件当首季商品。该数据用V2原始模型（含goodType/startTs/endTs等），客户端实际消费Common模型（含isSingle等），不能未经核对直接返回。有限库存、-1无限库存和是否新账号基准也需区分。真实时钟当前不在首季。

追溯该仓库shop.json历史有7次记录，最早2025-02-24为合并文件；其父目录原有CrisisV2GoodList.json。旧路径历史仅查到2025-02-15新增和合并删除，尚未取得首季限时目录。三次公开搜索及两次连接器代码搜索无结果，只表示这些查询未找到，不证明其他来源不存在。

## 本地证据和下一步

`.cache/crisis-20261127/shop-contract-v1/`保存metadata、目标/整函数解码准入、wire属性、实际购买路由绑定、参考原文/指纹及目录版本核对、public-close失败后的当前资源审计。REA输入/结果分别在rea-shop-buy-v1、mcp-shop-buy-v1、rea-shop-progress-v1、mcp-shop-progress-v1对应带日期目录；原始客户端代码、参考数据和采页不入Git。新采页在loaded-shop-detail-20261127-v1/capture.json。

上述为本报告开始时的研究状态；随后实现与实际验证见下节。旧失败、原文数据及没有取得的首季目录继续保留。

## 后续REA与解释边界

perm已由压缩元数据默认值和原版getter交叉核实：赛季为0，永久为1；另以已原生观察的任务枚举0/1/2作控制。最初按固定宽度读默认值产生无效结果，原件保留，未据此实现。普通商品可购数量由原版CalcAvailCount直接取Common.availCount，结合唯一物品上限裁剪；getter没有再减buyCount。因此getGoodList返回剩余库存，shop.info另存累计购买次数。

M164047/109642/109643/27980四处956字节REA实际59717退出0/public close成功。唯一性读取匹配item_table.uniqueInfo，剩余上限使用当前持有量；价格显示按当前order查精确档位。两个唯一物品函数的冻结体不能解，另采0x330f000一页4096字节后分析，9734实际退出0。M164044分档渲染596字节再采0x416f000一页，42147实际退出0；M164067进度条652字节复用已有0x4170000单来源页，未再次采页。两批REA63749/37536均public close成功/实际退出0，分别SHA-256 c5fc2017、356ecbc4完整摘要在本地证据中。

本轮共15个新方法4288字节；三次限定代码采页共12288字节，不是进程快照，不读取玩家、认证或活动热更新对象，不拼接同一函数的不同来源。采页无游戏API监听、界面输入或回调写入，index1/0063090c、APK/资源/表/TLS/离线及8秒守卫保持；index1关闭、index0与源/现用和旧QA保存SHA保持。分档渲染准备有一次inline exec覆盖脚本变量、一次输出目录预建不符合runner前置条件；两次都未启动REA，保留失败后使用新v2目录成功。

原版order默认1、按order取item/price和进度条选择已知；**progressInfo.count的官方后端累计含义、末档保存策略仍没有恢复**。实现采用显式finite-tiers-v1本地策略：每次仅一档、累计次数、order最多保留最后有效档，完成后从当前商品列表移除，直接再购拒绝。不能把该策略称为官方后端算法。itemSupplyTime原样保留为界面字段，没有把它猜作销售开始时间。

## 源码与保存

新增严格协议DTO、独立目录模块及原版购买领域服务，路由为crisisV2/getGoodList和crisisV2/buyGood。目录绑定客户端/GameData指纹、来源、适用起点、共享表真实赛季窗口；引用、类型、唯一上限、分档从1连续及重复ID均在启动前验证。正常/无限数量、家具、服装、材料、经验、龙门币和分档干员/信物通过既有事务发放；干员响应使用已有charGet获得流程，普通干员批量商品尚未准入。源数据中所有干员商品均为分档第一档。

同登录同seq返回完整原答复，新seq或新登录是新购买意图，不能用请求body的“领奖缓存”阻止第二次正常购买。持久购买流水、shop.info的id/count、分档进度和剩余库存一起核对；库存发放、扣币、事件审计、响应及输送回执在同一事务中提交，异常全回滚。

余额恒等式扩为“已验证任务币＋显式本地商店信用－本地消费－原版商品消费”。保留旧任务摘要、宝藏回执及本地商店配置绑定；领取、两商店交易、启动、在线恢复和离线新恢复均验证相关余额/库存，缺目录、改价、删账本、损坏布尔数量等在写启动前拒绝。没有数据库结构迁移，season.coin保持原值，未激活到现用保存。

## 当前实际验证

36项新商店检查及124项受影响回归共160通过，21776实际退出0；包含同seq/新意图、跨登录、并发限购、百万数量、唯一持有、分档charGet、到期边界/回拨、坏请求、发奖异常/坏响应、账号隔离、损坏保存及在线/新目录恢复。Ruff通过。最初32项夹具错误缺语音目录，随后31过/2夹具错误为获得凭证/默认语音遗漏及未计入任务自带5龙门币；没有放宽产品校验，修正夹具后33过，补3项边界成为36。所有旧失败输出保留，既有Starlette/httpx警告仍显示。

固定参考fcce42d的实际提交日期为2026-02-20T11:51:03Z；本地新目录明确标记reconstruction并从该日期起适用，不能回溯冒作2023首季目录。47永久、22第四季、4×6档引用准入通过；Common缺省值采用已观察CLR默认，title规范为元数据枚举名。参考库存是否等于官方新账号基准仍未证明；此前“尚未准入”探针原件保持。本次目录指纹f8c59c9288afbe17907ee0e28353adcaab12634777e9ae2a734a1fdc82049cd0，目录和原始数据仅本地，不发布第三方数据。

新工具verify_crisis_v2_native_shop.py在冻结14457902上建立47独立QA：先在首季预置任务资格，经confirmMissions真实领取各2400币，再移到明确闭季时间，逐项验证43普通与4组六档，共67次永久商品兑换。742次真实TLS请求（含4次预期拒绝）、三个有序服务组、冷启及真实备份新目录恢复一致，11647实际退出0；原始表/目录SHA保持。没有新原版游玩、自然战斗资格或官方认证，也没有测试限时商品真实目录交易。它们与合成数据中的限时窗口检查分别记录，不能把742请求称作原版客户端验收。

可重复入口（先加载tools/env.ps1，三个参数均为项目.cache内路径，新输出须不存在）：

```powershell
. .\tools\env.ps1
.\.venv\Scripts\python.exe tools/verify_crisis_v2_native_shop.py <冻结14457902缓存> <明确来源目录.json> <新输出目录>
```

新增本地证据为native-shop-tests-20261127-v1/v2/v3、native-shop-regressions-20261127-v1、frozen-native-shop-catalog-20261127-v1、native-shop-frozen-20261127-v1/verification.json及native-shop-summary-20261127-v1.json，均在.cache/crisis-20261127。原版shop UI/币弹窗、首季限时22件可靠目录、其他赛季、season.coin、旧季资源及新Windows发行仍未完成。下一先保存公开回读/新恢复检查点，再推进这些依据和一个原版代表，不重打旧关。

最终代码审查补齐分档唯一上限的类型检查及服装唯一上限准入，避免不完整数据导致运行时类型错误或重复付费外观。新增2个坏上限（布尔/字符串）检查通过，冻结目录只读重核仍准入、指纹不变，没有重复67次购买；当前合计38新商店＋124关联＝162不同通过检查（160成组＋2准入补验）。新证据native-shop-cap-validation-20261127-v1，当前Ruff和提交前源审查另记。

公开回读已完成：source b638093→main602fef3/treed6d9c9a，830公开文件和771源码395历史匿名下载、新项目目录恢复、全部SHA/Git/双fsck/干净通过，54309实际退出0。32上传对象/远程路径核Git SHA，31新增blob审查；两索引事后轮换、旧件保留。详github-checkpoints.md的同日商店检查点；本段晚于包，未新增游玩、发行物或重跑已过检查。
