# 自然商店供给：商品与投资栏位消费者

## 当前边界

上一阶段已完成一次主动放弃原生代表、源码私有二进制回读及新D恢复，属于实际进展；本阶段继续完整目标中的自然供给，不重打旧关、不恢复剿灭，也不再次购买或招募。源c05548c/业务3df4da4a/174文件、schema0034/75表为本段研究起点。

地图、事件和商店目前仍依赖明确方案；既有地图刷新消费者不能代替官方生成算法。本段只继续尚缺的商品/银行/锁栏位消费者。冻结APK/资源/索引/ELF摘要沿已验基线，未改客户端或原存档。

实际导入19表e915675d的manifest标注来源为本地镜像a550f5e、v077/77.6.0、client_verified=false；运行客户端为CN2.7.71/build190、V070。已有兼容适配及具体消费者不意味着这19表整体已获客户端逐项验证，不能省略这个版本边界。首主题NORMAL0、具体开放时点和已验证资格仍分别校验。

## 实际代码取得与保存保护

静态M155183 _InitSellGoodsList为0/392、M155184 _InitSellGoodItem为0/808，守卫拒绝，不把不可解码字节交给REA假分析。M155184此前也有同样缺口，本次不是新取得其静态实现。

在独立新D副本启动index1/<test-transport>/<test-device>，核APK47356684、冻结ELF3ece1e7b、资源/数据、TLS/离线与8秒命令。只从已核定文件映射读取RVA0x3f20000一页4096字节，不读堆/认证。0界面输入、0rlv2请求、6HTTP200；仅local_sessions变化，22完整用户和所有游戏表相同，201保护输入保持。worker会话91753实际exit0，所属ADB/TLS服务和index1退出，index0保持。准备时错误传入手写完整Git摘要被守卫在运行前拒绝，后改读实际HEAD；失败保留，不放宽检查。

具体代码页与保护证据在.cache/rogue-shop-supply-code-20261030-v1/{loaded-code-receipt.json,verified-code-only.json,native-results.json,full22-users.json}。代码页、伪代码、原始输出及保存仅本地，不入Git。

加载后两段分别完整解码392/392、808/808；还包含同页M155185 _InitBankItem 388/388、M155186 _InitLockSlotItem 408/408。生成独立8192字节ELF、10个完整方法种子，摘要a0526d664a20d855b2cbebbb467b5dba664e3e783de0f652a1a889b59e0885d4；不重写原ELF。

## 已取得的REA证据

首个会话mcp-shop-supply-loaded-v2公开close成功、实际执行58286 exit0/server0。第一次M155183返回provider_timeout，51.516秒；45秒观察结束不重排请求，待真实ACK后查询会话。M155184随后52.844秒成功，M155183在该真实错误结束后重试0.031秒成功。类型传播/重叠全局/Hotfix截断等警告保留。

- M155184，ev_fb01568bcae23b1b67f7187e186820967ebb4b46ec7b262677cc4c633acf69c0：默认分支遍历ShopContent.goods（+0x20）；按商品itemId（+0x18）查当前主题物品，按index（+0x10）匹配插件或调用ParseGoodsItemFromGoodsData/BuildTo，再加入sellGoods。这证明供应列表输入来自服务器对象；不是从全部图鉴选择自然商品，也没有价格/概率生成规则。
- M155183，ev_732f71398bc9b4ecb4b49690d098734b6a1fd23e565c033e00d47bc1eab0164e：默认分支清列表，依次_InitBankItem、_InitSellGoodItem、_InitLockSlotItem、_SortGoodsList；银行返回布尔传入后两者。Hotfix坏指令及尾部间接跳转不作完整实现依据。

同页银行/锁栏位的首次独立REA会话mcp-bank-slots-v1在尚无open/pseudo请求时达到空闲时限，completion记录server exit0、Windows wrapper42828/child40784现场缺席；执行句柄83913实际不存在，不能凭ready继续。保留该空会话，另建v2只分析未取得的两方法，复用原页，不重启模拟器。

## 导入表的明确事实及未完成

首主题bankRewards是五条：25/500为ADD_SHOP_POS，100/325为UNLOCK_ITEM，200为UNLOCK_WITHDRAW；gameConst.bankRewardCountType=HIGHEST_RECORD、bankMaxGold=999。这些是当前导入的具体数据，不代表所有主题/版本通用。尚未据阈值直接授物、修改reward状态、推算基础商品槽位或存取故障概率；须继续核银行/锁栏位实际消费者及发放/领取协议。

下一：取得M155185/M155186的真实REA结果并核metadata字段，按证实的依赖推进供给实现；自然地图/权重、银行完整交易、其他模式/主题、生命损失上传来源、Golden/长时断网/性能/Harmony/成熟EXE仍未完成。

## 投资栏位调用链收尾与源码

银行/锁栏位v2真实会话43126公开close/actual exit0/server0，复用原4096页，没有新Android读取。M155185默认从ShopContent.bank+0x14读open，关闭或null返回false；open时加入银行商品并从+0x15读取canPut。ev_1e26fc9945e93ba94ee6503f4f7ce0b0d939692ff2eddb55a9df27ee7b319739。M155186调用M33695(topicId,hasBoss)，循环加入锁栏位，银行是否打开只用于其isBankOpen显示属性；ev_2ba418b0a000d309831894bfe167864428bc3fc10835fd11b313c802e01cbbb5。两段Hotfix坏指令分支不作依据。

进一步静态M33695 GetBankLockSlotCount 464/464、M33696 GetBankRewardAccumulatedCount 152/152，单页8192包f79ca25830259c9746efe63d8bf5cdb3f1f11139953b6cb2c22626f552e207da、15完整种子。会话29297两次真实ACK（首个51.687秒、第二个0.031秒），公开close、actual exit0/server0，原包保持；相应Windows wrapper31544/child26608及银行v2的39252/10940现场缺席。

- M33695 ev_4dbc0cfd14145e97202b0920b6ddbd985493adc88d77bad17e4ee3c69f65d0a2：默认分支仅IsCurrentGameNormalMode为true、hasBoss为true、该主题有银行数据且bank.show为true才计算；总数为类型2的投资奖励数，减去bank.reward中已存在的对应rewardId数量。不是hasBoss=false时计算，也不读取余额/record/字典value来替代ContainsKey。
- 0x820c81c经冻结generic_functions→method_specs→methods解析为Dictionary.ContainsKey（method249378/spec33948），0x821bdcc为TryGetValue。字段+0x10=show、+0x20=reward由Bank metadata交叉核对。
- M33696 ev_b25d674cd9bdbb6d3a2cd28b6e933ed3d3a328c8f9102910dd58653565e82998：bank为null返回0；模式参数1取+0x1c totalPut，否则取+0x18 record。metadata的HIGHEST_RECORD/TOTAL_SUM压缩整数候选0/1、ADD_SHOP_POS候选2，与此控制流及当前表语义一致；原工具仍标注default_value_payloads_verified=false，不冒称已做运行时枚举独立读取或Hotfix验证。

新增只读FirstThemeBankRules、GameData.rogue_bank惰性入口：校验当前主题货币、上限、计数方式及显式奖励行，保留行序和指纹；奖励记录只读，不造缺失余额、不删除零值key、不按高余额补key。locked_slots接受调用方已验证的normal_mode布尔谓词及has_boss，不猜尚未单独解码的模式枚举映射；accumulated按表的语义字符串区分峰值和累计。快照检查自有领域的current≤record≤maximum、totalPut≥record、整数/未知奖励key，不接收客户端声明作为奖励凭据。未知奖励类型/缺表/越界明确拒绝，不静默开启新效果。

21项新针对检查通过，3文件Ruff/AST/diff检查通过；旧1316检查未受影响不为记录重跑。测试覆盖key存在值0、缺key与高余额不补key、非槽位奖励不解锁、三项显示门槛、null bank、峰值/累计、超上限累计阈值、未知/重复/缺失表字段、布尔冒充金额和不合法快照。保留既有Starlette弃用提示。没有新成功路由或存取款、发奖、自然池、原生栏位代表。

实际导入19表核对5条奖励、gold=rogue_1_gold、上限999、HIGHEST_RECORD、slot IDs bank_reward_1/5。目录hash d4c85bf5778d860c52946218fab8c3068271cd76aa078d77e668245a02bbc37f，业务3bb48495f0b510f6efbd17296b7feb47a299d698f3114c67174b9f5b180cf89f、175文件。保留新D副本上的22完整用户、75表和DB逐字节都不变，201保护输入保持；没有新增保存迁移、事务/授物/EXE。原保护场景未变，不为这项只读入口重复已通过的备份恢复/原生。

证据.cache/rogue-supply-consumers-20261030/{bank-rules-v1.xml,bank-table-facts-v1.json,bank-rules-frozen-v1.json,mcp-bank-slots-v2/findings-0002.json,mcp-bank-slots-v2/findings-0003.json,mcp-bank-slots-v2/completion.json,mcp-bank-rules-static-v1/findings-0002.json,mcp-bank-rules-static-v1/findings-0003.json,mcp-bank-rules-static-v1/completion.json}。第一次ask在ready之前被文件不存在拒绝，未排队；第一次M155183真实provider_timeout后新方法成功、原方法再试成功；辅助路径通配失败均不算产品通过。所有失败和空会话保留。

下一进入投资动作的真实请求/响应、一次存入的局内支付与永久余额/峰值账本、canPut/故障来源及奖励key写入顺序；再将已核定栏位接自然库存生成。基础商品数量、概率和故障策略仍须明确来源，不能从本次锁栏位数反推。新业务源码尚待本批私有检查点，当前最近完整远程仍是e4cec32；本段不是银行系统或自然探索已完整的完成声明。

## 私有检查点实际完成

2026-10-30投资栏位私有检查点实际完成：源7a59d07404afbd1400a2855103fc6fb081b00c71/业务3bb48495，私有上传d4f000b68d029d22faf0c3c70cc0c1cc23ca0799、父a82b0d3；bundle2174933字节，SHA256 71ad945f380b9d7d3a646ac815a73d672d95d7c027ce172c5b1d2875d7487c0b/Git blob4d528885bec3b704031a9ee66e3247c5f3b4ae96。实际浏览器下载双hash、新D510源码/198完整历史/Prompt/fsck/干净工作区恢复相同；512历史路径/2340blob扫描，无禁止路径或凭据标记。private/ref/树/README实际回读；新树4481b0fd8064667d9d78636176bb608255a59e78、README0c63e7ab62661837d3fb438b7da099149e4591e8，191条目，旧189非README条目及完整107732字符旧索引保持。普通Git非交互认证仍失败，不声称源码分支已推送。权威.cache/github-checkpoints/heartbeat-latest.json与rogue-bank-slots-20261030/upload-verification.json；仅本次双hash的C临时下载移D，旧下载不动。本包含21检查/只读银行规则及上批退出原生记录，未接银行交易/自然池或完整交付。完成文字晚于包，不因补完成文字重打包。下一投资真实请求/事务/永久余额和峰值/奖励key/canPut来源，不重复旧关/已过原生。
