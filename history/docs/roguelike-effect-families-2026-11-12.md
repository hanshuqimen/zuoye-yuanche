# 首主题效果分类与下一批范围（2026-11-12，研究）

完整目标ACTIVE；默认首层原生观察已经结束，不再重打地图或旧关。转向按完整类别批量推进，不能把当前21项默认基础池、65项已接纳定义或一条属性原生代表当作整个主题完成。

从本轮38用户恢复目录仅读取GameData，未打开玩家Runtime或修改保存。实际仍为19表e915675d/v077/77.6.0/client_verified=false，对冻结CN2.7.71/V070不称全表同版；限定rogue_1，后续NORMAL0和探索时钟1792645099的开放/资格仍须独立核对。

首主题265个效果定义包含245种RELIC、6种ACTIVE_TOOL、10种BAND和4种FEATURE，不应把265全部写成收藏品数量。当前费用/战斗属性/容量/金币/资源层五个适配目录的唯一ID并集为65，其他RELIC定义180；这180项不是默认可掉落物品，其他物品类型也不因此获得新能力。

按完整buff-key组合对180项分组得到47种组合，较大组如下。表中只表示数据形状，尚未证明整组都由客户端独立处理、效果已经生效、或具备普通节点供给资格。

| 完整键组合 | 定义数 |
| --- | ---: |
| global_buff_normal | 52 |
| immediate_reward | 26 |
| char_ability_new | 10 |
| global_buff_stack | 9 |
| change_reward | 8 |
| global_buff_stack_base_one | 7 |
| char_squad_attribute_mul | 6 |
| immediate_reward + level_char_limit_add | 4 |
| level_char_limit_add | 4 |
| up_reward | 4 |
| enemy_attribute_add | 3 |
| level_init_cost_add | 3 |

下一优先global_buff_normal整组的消费合同和完整条件，再处理immediate_reward多资源组合，避免逐件人工游玩。不能只凭键名把52项当无服务器效果：必须核具体blackboard/目标筛选/层数/有效来源及是否需要额外结算字段；混合键组合保留为独立未完成范围。

metadata索引SHA256 30c555d4479d4a0f708b9fc61aa4ecfeb945a169e4a82586e31d243afdaa4804只读核同。初轮SQL把整数methods.owner当类型名称匹配得到0，不是客户端没有相关方法的证据。scope-v2明确join types.id后286条Relic/Buff命名候选，按Battle/Global名称筛出30条，仍包含其他主题/模式，不能全套入首主题。只有候选定位，不是REA反编译结果。

回读既有属性报告，M84561 Init与M84565 _CreateRelic已取得完整默认消费者证据，本轮不重做。后续优先M81861 GatherGlobalBuffs、M81865 _TryGatherGlobalbuffIds、M84574 PreprocessGlobalBuff及必要的M84636目标筛选；先核实际完整静态指令与已存依据，再通过REA读真实路径，不能把protected/0字节或方法名当行为证据。本阶段尚未启动新REA会话或接纳任何新效果。

本地.cache/rogue-effect-families-20261112/{scope-v1/inventory.json,scope-v2/inventory.json,scope-v2/battle-candidates.json,inventory_v1.py,metadata_v2.py}保存实际分类、每项定义摘要、完整键集合和候选元数据。原表、官方方法信息和失败初查只本地，不进Git。0新业务/测试/Android/原生/战斗/EXE；下一以消费者证据推进完整类别及准确资格/供给，全部模式/成熟成品目标保持未完成。


## 全局效果消费者研究与接线开始

本阶段仍固定19表e915/rogue_1及CN2.7.71/V070，不称全表同版。52个纯global_buff_normal定义包含41个单buff、其余多buff，6项档案isSpRelic=true；c16确实没有relicParams记录，而且描述含首次关卡生命损失翻倍，不能用默认空条件补齐。初版global_inventory.py在c16抛KeyError，保留失败；v1输出明确conditions_present和缺项，不作接纳。c01/c02与首领相关m18的来源/后续合同本阶段独立待核，暂与六特殊及c16一起排除，42项只是本批能力候选，不是52项完成或普通池证明。

静态6消费者全部指令完整，32768字节片段SHA714550cf26a08bd12ef671b8cd56ff91770dc2b78d79d7ef85450ece0af844a5。首轮REA有片段外调用导致的坏指令截断，保留mcp-global-effects-v1，不能采信其截断数学/分支。增加22个已核直接调用标签/15只读未初始化页，代码逐字不变，容器SHA880575d2bf0eef115ae42bd8cdf201097976f42e8e6dec1e64b1dd55721a369c；没有RET或行为桩。更正后M81861入口、M84636筛选、M84562注册与M84568构造默认路径无坏指令截断；Hotfix分支/未知外部调用实现仍保留边界。

REA证据：M81861 ev_86b7b6d4667fb4524f6135d8718a6b6af10d7b8f67e2e62634d911f0ed1a145a；M81865 ev_7bf9016f92503bc42501dbd198dfaa5e95655a5ac27891e3dc019952aa437cde；M84574 ev_502986cac05e6aa56ee0cda00e23fe020899b2b5ec78777ae096f1bc2b50ed54；M84636 ev_b026d296e2d5970003e3c306ccc2d8a5317bda9f99c23e412b6e6ebe46bb324d；M84562 ev_9a963d1a1197d7701b9e2c57b141b5de594748d0a82c63b78e404892ce27aeb1；M84568 ev_2b0d0932c6d1f400275e248f1fd78906699b6fea9a868bc6a064099f6dab36f8。

仅搜Global名称会漏真实内部类GBuffNormal/GBuffStack/GBuffStackBaseOne，因此另按实际namespace查全类别/方法/字段。注册静态槽位需两次解引用，不能把第一个指针误作编码索引；类型标签1解析manager，方法标签6经methodSpecs/genericInsts解析_Register<三个真实类>，字符串标签5解析key。早期强套类型解析的越界错误和无意义char[]候选保留registration-values-v1，以registration-bindings-v1分标签结果为准。

具体函数7个完整指令位于12288字节容器；增加26直接调用标签/19未初始化页后SHAacb4be8cfdeefba6727815ed0dee70acad5c28764042ee362714567b9e4435f7，初始化代码SHA86f42b5ffbd668916c3abc5d9c412a93d0837f04e47a271c789be270ea468b81。M84948 520/520 ev_5d6e1aa6225bf576e46ccd142af8a587273ce9c5d56a0dfe2ebfe03914796951显示新建GlobalBuffData、key/黑板复制/可选字段/目标筛选、追加到输出列表；没有读取库存stackLayer来套乘数。M84947 104/104 ev_0c25d1710ef2fec7103e28590a9be7a47f633838d42e5183fa4a88351d1f7eda默认标志4，与M84574的两阶段筛选一致。M84952/M84956各776/776，ev_03bf508cc1ed7df93fe65f56d3d2b425c604bd8683480d0e76ae7ae61f9bfec7及ev_ad7bbf0432f9c8fc0ffc5833d8d89e238b243a6f3b3214f9bae77af05a072c26按相同key查找已有输出，再调用两种不同Blackboard合并方法，不能混用普通属性乘法。M84564 468/468 ev_6c100b435a5a7bf2f87534c8d72fa5ee1380e644155eb601fc1b4934fe7cbd36核字典/Activator/Init默认路径。列表扩容为间接调用，REA保留无法恢复jumptable警告；没有把未知callee或热更新分支说成已逆向完毕。

三会话wrapper及stdio子进程实际exit0，工件摘要保持；第一和具体消费者会话close正常。第二close报告cleanup_incomplete（launcher身份java与完整路径未匹配），不能用wrapper退出伪称close成功；针对所报WSL482实查/proc已不存在，未杀其他进程，观察证据rea-cleanup-v2-observation.json。45秒观察超时后请求仍在执行，均等同一ACK未重发；第一次在ACK到达前读取findings失败，后续改为确认ACK后读取，保留失败。新REA不读匿名内存、未启动模拟器或改客户端。

源码开始新增独立42项完整定义摘要目录与共享战斗准入，保留旧49属性目录、报价摘要和21默认基础池。只接可信显式方案的完整效果，不把解锁文本、库存展示或HTTP200当自然供给/原生效果。当前尚未做本批检查、正式38用户恢复或新原生；下一完成事务/回放/档案/报价集成，验证旧摘要和全部旧保存，再按必要性只做一个新代表。全主题及成熟完整交付继续未完成。


## 42项普通全局效果源码与保存验证

业务8fa5584758c180ee8cb52dea1bd0c12d3959e08980f64255894d6542e8beae5d，203个Python，schema0037/78表。新增rogue_global_buffs逐项冻结42个完整效果、relicParams、物品类型，档案特殊/登记时间另校；rogue_battle_effects将其与旧49属性能力按原目录分别准入，不能把完整黑板压成一个通用乘数。显式商店使用独立global_buff报价材料；无新类商品的历史摘要保持，数据或作用域变化拒绝。可信战斗奖励、因果回放、唯一库存和图鉴发现接同一准入，原无叠层count1/layer0、招募屏障、事务和幂等守卫保留。接纳预算65→107仅为效果能力并集，不是官方数量上限或自然出现池。

10排除项仍为六isSpRelic、c16缺条件/生命损失合同、c01/c02及m18来源待核；没有从排除结论推断客户端无对应代码。旧49目录原文件不变，21默认基础池、固定事件与商店自然资格/价格来源不扩，未把42种能力默认为商店库存或解锁。

17项新检查首轮过：完整定义/布尔与数值/额外效果/目标筛选/条件缺失拒绝，特殊和登记时点，旧报价对新能力目录独立，新报价绑定本类摘要，叠层/重复报价拒绝，购买增量/同键与新键重试、永久阵容和后续招募费用保持、并发一次扣款一次授物、投影失败全表回滚、损坏库存只读启动拒绝、显式战斗奖励一次选择及重启/真实备份。124既有属性/费用/商店/图鉴/战利品/默认供给相关检查过；两XML用例ID去重共141，不累加重跑，Ruff11及diff检查过。原有httpx/Starlette弃用提示保留，不称全游戏零bug。

matched-verification-v1/78683实际exit0，在上一已恢复38账号保存的新D副本使用完整19表e915，限定rogue_1/NORMAL0/1792645099。42定义与源码逐项摘要同，n03/n05/n10/n12/n14/n15六登记均为1655323200，时点已开放；42分为32/10两份明确QA报价/奖励组编译与保存结构往返，仅零价格效果证明，不是发物或官方资格。10项排除报价全部拒绝。完整38用户视图与78表所有原始行完全保持，25肉鸽/0普通战斗不变；真备份恢复、冷重开、再次新D恢复同，39保护输入及源码保持。0新账号/探索/战斗/Android输入/原生/EXE。

最终证据.cache/rogue-effect-families-20261112/final-v1/{verification.json,final-checks.json}及matched-verification-v1/{verification.json,full-users38.json,restored-new-d}。REA实际会话/指令/原数据仍仅本地；三个Windows wrapper/stdio PID当前均缺席。旧阶段初查和失败保留。本批没有新源码测试失败，研究准备的c16缺条件、过早读ACK、片段外截断及第二close身份错误仍是本阶段失败记录。

当前只是源码/自动检查/正式表保存兼容通过，客户端全局效果消费仍待一个新代表，不逐件或重打旧关。先保存私有源码检查点并实际回读/新D恢复；自然池/资格、叠加及即时多资源效果、事件/所有主题模式、完整原生/Golden/断网两小时/性能/Harmony/成熟EXE全部继续未完成。

## 私有源码检查点完成


2026-11-12 全局普通效果源码私有回读完成：sourceef9005054eeff9d540a830dc263b9430732b5f1b/业务8fa55847/203Python/0037-78→privated28fdea1376064ac6f4cfee6c9089a100c439e62，父ce757eb/treee27ff2de363649ef7e6a2ebdd2ea5e69db5e95bc。bundle2935579字节，SHA256 b4bbadcbaf9a476c25940cac1b0fbbde47089833992bf3d20739d846aa5adbd2，Gitblob76d486595e947c1c22734fd560d9ec94408c7c2a。635源码文件/310完整历史，新D完整tree/blob/Prompt/fsck/clean同；637历史路径3474UTF8 blob扫描无禁入/凭据标记。旧253非README项保持，README新增1511字节范围前缀，原174539字节全文完整后缀保留；远端256项，README blob e693ad0512dbb0b77223debcc95b587a756b716c。

本次普通Git禁交互probe实际exit1无登录/无ref；连接器expected_sha+force=false续private main，非源码分支直推。私有/ref/父/tree、manifest和README完整内容实际API回读同；授权IAB浏览器2新tab4访问精确提交，Download raw file真实事件入站，SHA256及Gitblob双核后，仅本次新C临时下载移D；未改权限、读凭据或访问被阻止8080。verify_remote实际exit0；源历史全同的新D恢复证明齐全后才轮换heartbeat-latest/local-latest，旧索引previous-*及所有旧包保持。39保护输入除授权轮换索引外保持，业务源码保持，另有protected-inputs-after-index-rotation.json。

权威.cache/github-checkpoints/heartbeat-latest.json及global-buffs-20261112/upload-verification.json；详细prepared/old-remote/readme-preservation/pending-commit/api-readback-summary/remote-meta/received-web/restored-remote-ef90050均本地。包含42新能力、141检查（17新）、正式19表/38用户78表真恢复与REA消费者及全部失败记录，也保存上轮QA38默认首层原生记录，但该记录不是新全局效果原生证明。本批0新账号/探索/战斗/Android/原生/EXE；能力总并集107/245，尚有138项RELIC完整效果未接纳，不能当成自然池完成。当前完成文字晚于包，不重复文档bundle；下一一个新效果原生代表和准确资格/供给，全部成熟交付目标ACTIVE未完成。
