# 特殊招募与费用合同（进行中）

当前：16保证FREE券的基础招募及无模组晋升路径/schema0031已实现，71新+190相关共261不同检查、冻结736模板/23HTTP及备份/新D74表恢复通过；四星初招v34原生代表/恢复已验；临时E2/模组/官方概率/另外4特殊及完整交付仍未完成。业务94e03978，末尾保留全部阶段失败与恢复依据，995ddf2已私有回读/新D418文件121历史恢复，完成记录另存。

基线eb2a041，业务31f0466a/schema0030/74表，普通16类的161针对检查和c258私有回读/新D恢复保持。上一轮为实际进展。本轮不恢复剿灭、不重复旧关或晋升代表；先核实特殊候选及费用合同，再按类接线。完整主题和成熟交付仍未完成。

## 当前依据

- 冻结CN2.7.71/e915675d的20特殊券：16个职业red/sp分别明确保证六星/四星临时招募；premium保证精英临时；另3个discount描述为部分干员直接进阶，并非普通希望折扣。不能从英文后缀推断效果。
- NativeTypes核对RecruitChar.type是RoguelikeCharState，population/isUpgrade/troopInstId等独立；枚举名称包含NORMAL、UPGRADE、UPGRADE_BUFF、UPGRADE_BONUS、FREE、ASSIST、THIRD、MONTHLY、THIRD_LOW、MERCENARY。元数据受保护默认数值未经消费证明，不把原始字节当已验证枚举值。
- 全局预定义引用实际有431个FREE、5个THIRD_LOW、6个THIRD；canBeFree和uniEquipId独立，不能把全部角色表或用户已有干员当免费池。FREE的Amiya样本canBeFree=false，是过滤条件仍需核对的反例。
- 现代主题detailConst的类型存在RecruitData(recruitPopulation/upgradePopulation)，但本次实际导入的rogue_1详细字段没有该费用表，predefinedLevelTable为空。类型存在不证明具体版本表内有值；现有普通费用来源边界不变，不据此替换已验策略。其他主题只做结构对照，不推广为其玩法规则。

## 本地证据与正在处理

`.cache/rogue-economy-20261026/{special-contract-inventory.json,special-native-fields.json,predefined-special-contracts.json,detail-cost-contracts.json}`；官方内容仅本地。索引30c555d4/ELF3ece1e7b/metadata bf14421b守卫保持。

新REA bounded code页仅M33665/33668/33669，artifact58396225。manager句柄38912及实际ready wrapper25404/child31960，M33669请求正在同会话处理中；观察超时不会重启。新业务尚未修改，原生/发行物0新增。

## 实施候选与实际发现

上述为研究初期状态。REA38912现已实际exit0，公开close通过、代码页保持，现场25404/31960缺席。M33668/69是招募藏品新激活判断，并未返回费用公式；M33665默认分支读取当前population对象，Hotfix分支有bad-instruction截断警告，不作为新费用推导依据。3结果分别为ev_f8f2cd61、ev_eafe5926、ev_1fc63ced，本地mcp-special/findings-0002至4.json。

已实现20特殊券/374有效预定义候选静态合同（368 FREE、6 THIRD），36静态针对检查通过。随后开始16个red/sp保证FREE候选事务：schema0031约束、随机选择后冻结、独立临时干员模板、晋升历史/费用/商店接线；其余4类未启用。养成模板使用实际角色阶段上限及主题两级技能上限，满潜/信赖为明确本地基础适配，原生验证待做。预定义uniEquipId保留在目录但模组等级/适配尚未核实，不伪造模组。正式临时出现概率、premium、随机直升与费用修正仍未完成。

游戏行为交叉资料：[集成战略社区记录](https://prts.wiki/w/%E8%82%89%E9%B8%A1)与[临时干员状态说明](https://m.prts.wiki/w/%E9%9B%86%E6%88%90%E6%88%98%E7%95%A5)记载临时初次招募免费、晋升照常消耗及精一/精二养成状态。这是社区观察，不冒充官方协议或冻结模组配置；筛选/引用/字段仍来自本地表与REA。

阶段失败保留：初始19事务夹具gold缺id被导入守卫拒绝（free-transactions-v1），未启动业务；修正夹具后16券激活/冻结/取消及免费进阶事务通过，2付费进阶报503（v2）。追踪到实际共同缺陷：同券有多付费晋升选项时，总费用校验按“已使用券”累加所有候选。改为训练账本指定的(ticket,option)，未削弱希望限制；v3两分支通过，并新增两个普通已拥有干员的同券反例。原生/发行物0新增，迁移/异常及完整相关检查继续中。


2026-10-26保证临时招募基础事务已接：16个red/sp职业券按明确FREE池生成并保存1个匹配候选，不变更永久阵容；首次0希望，独立精一模板/精二晋升及专精，正常券收基础晋升费、免费进阶券0费；模组仍未接，不声称完整临时系统。20特殊静态目录/374候选（368FREE/6THIRD）与canBeFree等引用受约束，premium/3随机直升仍拒绝。选择使用明确本地等权策略，冻结候选不重抽，不冒称已还原官方概率。schema0031/74表，0030约束迁移保持旧行/paid训练记录及原子回滚。修复实际共同缺陷：多付费晋升候选原按券累加所有费用，现按训练账本实际(ticket,option)累加；两个普通已拥有干员反例及临时4/6星反例通过。最终71新+190相关共261不同用例通过；用例按最后一次实际结果去重，失败/夹具错误保留，不能把各轮数量直接相加。16券激活/冻结/取消、临时招募/两类晋升、并发/事务回滚、坏模板读前拒绝、旧/新训练编队与0030迁移通过；Ruff/diff-check通过，既有Starlette弃用警告保留。冻结e915675d 736模板（包含静态5星模板，16保证券实际只覆盖4/6星）检查及23HTTP断言通过，两晋升候选只扣选中3希望、临时干员没有进入永久阵容。原生v32/account4及v30/account3完整rlv2保持；旧0030行除版本外保持、备份/新D74表及完整新QAuser相等、原数据库字节及80保护输入保持。冻结核验脚本在已完成HTTP后误读player.id报KeyError；保留原目录，按ORM实际run查询恢复后半段，不重放HTTP。第一恢复器误猜request_receipts报StopIteration，改为m.Receipt.__tablename__并现场回读21唯一成功收据；2同键重放合计23次调用，前缀断言已执行，由失败行/脚本SHA和收据/最终状态交叉记录。两次恢复登录仅自有新QA账号，其他账号和原保存保持。REA38912公开close/实际exit0、三默认消费者与代码页SHA保持，M33665 Hotfix截断不用于推导公式。0新原生操作/实际战斗/EXE；基础养成模板的原生、预定义模组、官方权重/普通券自然临时概率、其他4特殊券、费用修正、正式供给及全游戏交付未完成。业务94e0397846b563b3c5ef70abea6b9c217d1b6843c3600da6ae3ee5eeac0f9ae7；证据.cache/rogue-economy-20261026/{free-validation.json,free-frozen-verification.json,free-frozen-verifier-resume.json}。下一步保存源码检查点，再准备一个新FREE原生代表，0旧关重打；旧c258私有包仍保留，新源码尚未远程回读。


2026-10-26保证临时招募检查点995ddf2完成私有实际回读/新D恢复：418自有文件/121源码提交/420历史路径/1521blob扫描，禁止路径/凭据标记0；完整包1595247字节，SHA256 e94642da9cd6f0b58d5bd2561b7444072acd931334c19287b7bf2710fcefdf1f，Gitblob a52c8d35fdbb337cf5051221316de96961ba6290。上传/索引2216eb00以旧d1e3f033为父，163旧非README根项及旧索引全文保留，根项165，实际private。Git CLI关闭交互仍无既有凭据，因此使用已授权完整bundle备用路径，没有称源码分支正常push；没有强推或公开仓库。精确提交GitHub网页下载与两种SHA一致，新D恢复418源Gitblob/完整121历史/Prompt/fsck/干净工作区相等；默认浏览器短暂C下载仅本次新文件再次校验后移D received-web/browser-original-995ddf2.bundle，旧包/下载/保存/发行物保持，无权限/设置/凭据操作。两个网页截图分别保留995标题/源码/业务哈希与完整SHA/261检查和无模组基础范围，组合核对，不用单张裁切图声称全部可见。证据.cache/github-checkpoints/rogue-temporary-free-20261026/{upload-verification.json,checkpoint-web-proof.json,restored-remote-995ddf2}，权威heartbeat-latest/local-latest已指995。包内业务94e03978/schema0031/261不同检查、16保证FREE基础事务/多选项晋升费用修复、736模板/23HTTP断言、核验脚本后半段失败及不重放恢复、原保存/新D74表/80输入保持，0新原生/实际战斗/EXE。新FREE原生/模组/官方概率/其他4特殊/费用修正/正式供给和全交付未完成。完成记录在后续本地提交，不在995源包内，不因此重复生成纯记录包。


2026-10-26恢复FREE原生现场：v33曾由新QA账号6/12HTTP准备同一清道夫FREE候选，六导航故事仅QA前置/无奖励；初次短HEAD被守卫拒绝，随后完整e812419启动，SDK连接/一标题输入后screen02为过渡黑屏。后续继续时74668句柄缺失、实际2404缺席、18443/自有ADB均无残留，ldconsole现场index1停止/index0保持，最终退出码及native-results未观察，不推断退出原因。实际14HTTP全200/0rlv2操作，券3 ACTIVE、只有原初干员/无训练。v33及旧数据全部保留；v34新D副本74表/完整rlv2精确相等、同候选char_149_scave/option2保持、91保护输入；0新发券/购买/重抽/战斗/EXE。证据.cache/rogue-native-20261026-v33/{prepared.json,requests.jsonl,screen-01.png,screen-02.png}及v34/{prepared.json,prepared-state.json}，下一步继续该未消费代表，不重跑旧关。


2026-10-26保证临时招募v34代表完成：沿用v33未消费的同券3/同清道夫option2，未重发/复购/重抽/战斗。原生screen14-15蓝色临时标记/招募0希望/精一60/双技能7可见，screen16招募动画，screen17售罄/2干员，screen19离店回图、screen20临时卡片及技能保持。40HTTP全200、恰2rlv2操作recruitChar(3,2)/shopAction(leave1)，训练历史0/探索2人、永久阵容无清道夫；全部资源property不变（希望cost6/max6、可用0），无新战斗/EXE。94443实际exit0，实际36080缺席、服务/自有ADB/index1正常停止；91输入及Python源94e03978保持。Runtime完整rlv2重开、备份恢复74表及新D74表/rlv2相等；SQL按account/operator/run归属核对全部74表的其他账号/全局旧行相等，旧原生账号3/4同步保持。errors0041无Exception/JSONPath/Lua nil，不能据此说所有UI无bug：screen10主页公告出现“页面打开失败”toast，40HTTP200仍不能证明WebView页面成功，下一步独立核对公告/页面合同；SDK初始黑屏经一次Back回登录页，成因未判定。screen05外观沿用SDK协议标题，实际点击service链接后screen06及GET/protocol/plain/ak/service确认内容是TerraLocal非约束性本地存档说明，随后只记录本地账号6版本确认，无官方协议/认证请求或官方认证数据。六QA故事前置未发故事奖励。v33最后退出码和收尾仍未观察，保留14HTTP/0rlv2及现场，不以v34正常退出覆盖。这里只验一个四星FREE初招，无重复旧关/免费进阶/付费晋升原生；六星/临时E2晋升及预定义模组/官方概率/另外4特殊券/费用修正/正式供给/全交付仍未完成。证据.cache/rogue-native-20261026-v34/{verified-native-free.json,summary-0040.json,errors-0041.json,native-results.json,requests.jsonl,screen14-20,free-native-new-d-reopen}，source995ddf2已私有回读；本条新原生完成记录在其后提交，不能冒称已在995包内，后续源码检查点一并带入。
