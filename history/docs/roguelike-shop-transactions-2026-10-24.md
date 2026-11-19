# 傀影商店交易（2026-10-24）

本阶段遵循用户再次确认的代表检查/批量同类接线安排，不恢复剿灭、不重打旧关。源码新增独立商店报价/访问/支付/库存/招募券绑定、shopAction路由及schema0027（73表）；报价来自明确的服务端方案，当前没有启用猜测的官方随机商品池。普通八职业券接同一事务，藏品、银行、刷新、回收、批量/混合操作、楼层及含商店的完整结束统计未完成；未支持分支明确拒绝，不用空成功替代。

## 原生合同研究

v22从停止的v21建立新D副本，72表初始相等，仅syncData投影明确QA商店；5金币医疗券为自定义报价，不证明官方价格/出现资格。商品、名称、图标、价格及确认弹窗显示正确，真实请求POST /rlv2/shopAction，buy=[qa-medic-1]/recycle=[]/leave0；当时业务未接，实际501及原生断连提示保留，不能标购买通过。只观察一次新分支，没有为了离开请求重登或重复购买。22请求21×200+1×501；原句柄64708正常exit0，所属服务/ADB/index1正常停止，58其他账号表、69保护输入保持，只有local_sessions变化，0新战斗。

加载商店后只读取两个已校验ELF文件映射可执行代码页，不读取堆/凭据。M155177 LoadData的440/440字节及M155184 InitSellGoodItem的808/808字节线性解码，REA真实句柄97503/5781均exit0、stderr0；evidence分别ev_fc5ebfd897c75a5553123410b9165f810d8241959dfd8623a0356cf666c46e10与ev_5cab97bfdeb3e6a72531879ea0553002645701b59acab399a9ee53c3b01590c5。坏指令截断Hotfix/类型传播/全局符号等限制保留，不能把线性覆盖说成整个控制流还原。两个商品模型构造方法155154/155156静态0字节解码，未启动提供器。当前仅投影剩余商品，售罄卡/ban语义待进一步核对，不猜其数值。

## 实现与检查

报价引用实际导入版本的源石锭与已接纳职业券，明确槽位/价格/来源/hash；客户端只可提交商品索引。独立RogueShopVisit保存方案、节点/账号/地图/数据绑定、进入前资源及按序购买与券ordinal。场景/战斗/商店共享实际路径及资源重放，购买与扣款、库存、创建并激活券及请求收据同事务；重复请求/新seq不再扣款或发券。当前招募未完成不能再购买或离开。旧26迁移只添加新表，不重建父表；启动和恢复前只读验证报价、所有权、时序、支付及发券绑定。未改原存档/发行物，无新EXE。

22个纯组件检查0.13秒通过；首个交易组7通过1失败，原因是测试复用旧初始化close请求号，修正测试为独立号，产品未放宽。关联组116通过4失败（76.11秒）：新增备份测试误用返回path键；另三处旧schema夹具残留新shop表/目标表数。按真实BackupService name接口及历史schema还原修正，旧失败保留。随后36项商店/迁移/初始化关联检查16.62秒通过；另一个7项前置/旧迁移组6通过1表数量断言失败，改0024升级新增三表的事实后该项1.02秒通过。各组有重叠，不相加或称完整游戏回归。新账号隔离/伪造价格/未支持动作/缺表只读拒绝在6通过组中通过，既有Starlette警告保留。Ruff及diff空白检查通过。

真实e915675d冻结数据，独立D盘QA方案覆盖8种职业券；29HTTP=27×200+2预期409（未处理招募离开/余额不足）。实际扣5，金币6→1、HP4、11张券（3原券+8新增），每个购买/新seq重试/关闭券及剩余库存与完整同步delta一致；重开完整sync相等，备份恢复73表一致，74保护输入保持，0新战斗。后七个零价为明确QA边界，不是官方免费商品。首个辅助因settings.save已建profiles而copytree失败，未复制/修改原DB，保留失败目录；改新v2目录合并自有配置后通过。一次启动将Git短SHA传给完整SHA守卫而提前拒绝，未启动服务；两次路径检索错误和旧fixture问题均不当产品通过依据。

本地证据.cache/rogue-shop-20261024/{component-validation.json,frozen-http-validation.json,related-tests.txt,migration-and-shop-tests.txt,preflight-and-old-migration-tests.txt,rea-loaded/,rea-goods/}及.cache/rogue-native-20261024-v22/。v23已从原v10复制68表并迁移到73，既有行除版本保持，只在新QA副本准备两个SHOP节点和明确报价；尚未原生启动。后续一次修复后原生购买/招募/离开，完成后再更新本报告，不能预填通过。全目标仍active，正式商品池/高级效果/楼层/全主题/成熟EXE等未完成。

## 后续原生验收与售罄合同

bb312b0/业务e091e8b5的v23实际一次进入SHOP、购买医疗券、展示备用医疗候选、明确放弃此券、回商店、确认离开/回地图；真实moveTo→shopAction(buy/leave0)→closeRecruitTicket→shopAction(空列表/leave1)，75请求全200，金币6→1、HP4、4券且新券DONE、商店FINISHED/下一节点可达。未进入第二商店或战斗，不重玩旧关/剿灭。原句柄19107真实exit0/所属服务ADB/index1正常停止；59其他账号表/72保护输入保持。错误摘要未发现Exception（有界当前进程日志范围，不证明全游戏零异常）。当前业务4e1eb036c10f1fa6a6aff1db6254cc5ea4fec49a328095e8bc166f551117c474，在新D native-reopen目录重开实际停机副本，73表全行保持、完整rlv2等于末次原生快照；实际DB SHA及完整输入清单登记于本地validation.json。没有额外冷启客户端/新EXE。

本次只取新需要的两个可执行文件映射页，M155154/608字节与M155156/360字节完整线性解码；REA句柄7715/48963实际exit0/stderr0，证据ev_3b868f46dff9a4c5a045109f539c709cf15cca49c7c47cc34576962cee661dde与ev_4cbd397e9880fc1245bbb32c7be85dfcd4409fb647b85771361cfdc169a47a1e。默认ParseGoodsItemFromGoodsData读取Goods.count(offset32)<1，再由BuildTo复制到ViewModel.isSoldout(offset113)；ban的枚举数值/Hotfix完整行为仍不扩推。依据此新合同，将已购槽位保留count0，避免后续商品左移；此前原生通过的是剩余商品列表投影，新的售罄卡视觉没有再游玩确认，明确保留这一边界。只补1个受影响的付款/商品槽位/差量/恢复检查，1.53秒通过、Ruff0，不重复未变化的全量检查/八券HTTP。更新仅wire槽位，原购买/存档摘要/重启事实保持。

本地新增证据：.cache/rogue-native-20261024-v23/{native-results.json,requests.jsonl,summary-0033.json,errors-0034.json,screen-09..15.png,loaded-code-receipt.json}；.cache/rogue-shop-20261024/{validation.json,soldout-contract-test.txt,rea-goods-loaded/}。研究、QA、源码、自动检查和原生范围分别保留。Git普通登录本轮明确缺少可用凭据（禁止交互探测），GitHub连接器现已能读取私有仓库，后续按可用连接保存完整历史检查点，不提取凭据/改权限。

## 私有检查点完成

2026-10-24商店检查点已完成：源码722a616（业务4e1eb036），386文件/96提交/387历史路径/1257blob经禁止路径及凭据标记扫描0。私有连接器可用，正常Git缺凭据不能普通推送；完整bundle通过连接器上传8b5410a，原148项保持。连接器大文件正文为空/UTF8错误保留，未把metadata当回读；精确提交的已授权网页raw下载经SHA99b742be核对，新D恢复386文件/96提交/fsck/完整历史/Prompt通过，句柄64062真实exit0。索引ef5ba445只改README前缀，旧正文及149非README项保持；没有改公开性/权限/凭据或运行存档。下载由浏览器默认C再暂存D，未改系统设置/删下载。实际索引.cache/github-checkpoints/rogue-shop-20261024/{upload-verification.json,checkpoint-web-proof.json,restored-remote-722a616}与heartbeat-latest.json。随后记录文档不预称已进入722包；业务代码和原生/失败报告已在该包。全目标仍active，下一步正式供给/藏品/楼层等，不重复商店购买或旧关/剿灭。
