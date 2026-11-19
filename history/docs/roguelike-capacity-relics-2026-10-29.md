# 编队上限藏品：六条获得效果与因果回放

完整目标继续、未完成；不重打旧关、不恢复取消的剿灭。本轮从自然供给依赖继续补齐完整物品效果，不用未知地图/商品权重造默认池。上一轮历史资格报价适配及私有回读c8b1dd4/e2864be是实际进展，未重复研究已完成的M154269。

## 匹配范围与依据

业务bcd927b4eb2afaf897911f010b4e1449d91808fd713fff9a1fef5e7f0b317fc5，171业务Python文件，schema0033/74表不变。固定CN Android2.7.71/build190、实际19表e915675d8d8a1cc97df8fa46eed27ef1bdaa9d1b0fdb07461dcabda36271ae29；rogue_1/NORMAL0，正式QA时间1792644559。没有新作战关卡或原生输入。

按实际archiveComp.relic.relic而非全部relics筛选，a35/a36/a37/a38/a39/a40的完整单一效果均为immediate_reward，目标rogue_1_squad_capacity，数值分别1/1/1/2/2/3。目标items.type为SQUAD_CAPACITY且gameConst.squadCapacityItemId指向该物品；六项均无enroll且不是特殊变体。全条效果、选择条件、物品类型/条件文案、图鉴引用和目标资源完整行摘要逐项绑定，不能仅看到一个数值就忽略其他效果、条件或隐藏路线。

本次数值依据为冻结结构化GameData，复用已有休整capacity资源、完整同步及战斗编队准入路径；没有解析自然语言来猜公式，也未增加新的客户端请求字段。沿用已记录REA/原生基础协议依据，本阶段未新增REA、模拟器或藏品图标/动画验收；此前M154269仅证明进度消费，不能当成本类效果或自然资格的证据。最初跨整个relics做单buff盘点含分队/胶囊，因此只把后续真实图鉴六项完整提案计入本批。

## 实现和兼容

新增不可变FirstThemeCapacityRelics，校验定义和整数边界后计算现有资源值加固定增量。编译明确服务端商品时使用独立capacity策略及规则摘要；旧票券、四减费和49属性商品的摘要构造保持不变。机械支持预算从53扩至59（4费用+49属性+6本类），不代表59件自然可取得或已逐项原生实测。

购买在同一数据库事务中扣款、记购买收据、授予一份layer0库存并增加squad_capacity；失败整段回滚。完整状态从有序节点/购买日志重建时，每个真实购买恰好应用一次增量，然后继续后续商店、休整和战斗。新增类不会生成费用修正事件或空招募券，既有待办招募屏障仍生效。重复请求、并发请求不重复加成；无购买来源的额外资源值会被拒绝。

获得投影接永久图鉴state2；放弃/终局保留发现，新局只使用本局起始容量，不继承旧局增量。默认终局验证接纳这类已验证效果，其他未知分支仍拒绝。本批不改变已保存旧响应、旧报价、旧收据或旧结算政策，没有迁移或追发旧奖励。使用save-systems技能核对权威数据、事务写入、历史重建和恢复边界，保留既有SQLite事务/WAL实现。

新六件尚未加入正常商店基础价格目录；现有53条价格/排除与历史资格报价入口保持原范围，本批实际获得只来自明确的QA报价。六件解锁条件、自然取得、价格/权重不能从effect或一份QA库存推导。正常地图/池、银行/折扣/刷新仍未完成。实际银行常量可见bankMaxGold999、bankDrawCount/Limit0和空bankCostId，但这些不能代替银行协议或经营规则，本轮未新增银行操作。

## 检查与实际数据验证

23项新增检查通过（v2中19项、v3定点修复3项、v4新增1项），180项受共享报价/库存/回放/图鉴/终局修改影响的既有检查通过，共203个不同检查；10个修改Python文件Ruff通过。覆盖六条定义、输入/溢出、整体定义/选择条件/图鉴/目标失配、原子增量、重复/两个Runtime并发、招募待办屏障、不同藏品先后获得、回滚、历史损坏、放弃新局、重启及实际备份恢复。7人编队在容量6时拒绝，应用a35后容量7时允许；没有新开战。

首次合成夹具缺gameConst导致17失败/5setup错误；补齐显式绑定并处理训练夹具覆盖gameConst的层次后，19通过/3因测试误用squadCapacity字段失败。按真实player.property.capacity改正后3项定点通过；初次替换脚本误估引用数量而断言失败，未写文件，再按实际8处修正。Ruff一处长的函数内import布局失败后移到函数入口；XML/失败文件保留。Starlette弃用提示与并发测试中的Pydantic alias警告保留，没有用测试数量证明零bug。

新D实际数据副本先核对19个完整用户及74表与原基线相同；仅新建QA账号20，手工设置系统入口关卡作为夹具，准备单SHOP地图和六件零价QA商品，不伪称自然通关/正常商店售价。通过现有HTTP moveTo/shopAction逐件获得，容量6→7→8→9→11→13→16；每项delta与sync相等、重复新序号不再增加，本体troop和源石锭保持，库存恰好新增6件且初始招募券仍3张。资源计数16不证明原生可选择16人；既有本地战斗请求12槽预算未改，完整上限/原生表现未在本阶段补验。

旧19用户所有字段保持；完整20用户/74表在Runtime重开、真实BackupService备份恢复和新D恢复相等。原始全部74表、旧收据及183保护输入未变。新D仅QA授物6件，本阶段0原生点击/招募/战斗，没有新EXE。正式规则摘要235400d28c132ef2ad27e0300da38e25f9c4f231cfd96d74d5652e9f9cd5dbde，QA报价92e1a023d0512767e7c912bba09b080141c0deeb36b619107e752abe4a90df0b。

下一保存实质源码私有检查点，随后只做一次新获得/容量显示代表，或补本类实际价格/资格来源，不重复旧关、旧属性代表或旧REA；其他效果/自然地图及全部模式、成熟EXE、完整Golden/断网/长时/性能/Harmony仍未完成。

## 证据入口

.cache/rogue-natural-supply-20261028/{capacity-proposal-v1.json,capacity-v1.xml,capacity-v2.xml,capacity-v3.xml,capacity-v4.xml,capacity-regression-v1.xml,capacity-qa-v1,capacity-before19-v1.json,capacity-final20-v1.json,capacity-reopen20-v1.json,capacity-restored20-v1.json,capacity-new-d20-v1.json,capacity-restored-new-d-v1,capacity-verification-v1.json}。官方数据/描述、存档/收据、截图/代码页、日志/缓存只在本地，不入Git。工具检索中Windows通配文件路径失败后改为目录和-g筛选；没有据截断输出作整类结论。

2026-10-29六容量效果完整私有检查点完成：源c1fbc16d28a92cadcfa6ae4cd068242752d48ab3/业务bcd927b4，私有上传88ffdb567f8b783c7a715c02bac7156cc1eb343e；bundle2061588字节，SHA256 e2e43de8eb973aac3a27939088b9a84a0cba5a91a544fdd01fdab12222d42bd6。实际浏览器下载双hash，新D491源码/183历史/Prompt/fsck/干净工作区完全恢复；493历史路径/2146blob扫描，无禁止路径或凭据标记，旧182非README条目及完整原索引保留。权威.cache/github-checkpoints/heartbeat-latest.json与rogue-capacity-20261029/upload-verification.json。含203检查/正式20用户恢复证明，本阶段0原生输入/战斗；正常价格/资格、自然供给/地图和完整交付仍未完成。完成文字晚于包，不再为完成文字打包；下一一个新获得/容量显示代表或本类价格依据。
