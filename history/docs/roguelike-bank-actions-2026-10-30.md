# 投资存取款：协议观察与事务前置

当前完整目标未完成，上一goal turn是进展：投资栏位只读规则、21检查及私有源码回读恢复已完成。本阶段起点a004e8d、业务3bb48495/175文件、schema0034/75表。继续真实存取款与持久化，不重复旧关、剿灭或已通过交易；应用save-systems技能确定权威纯数据、版本、事务边界及旧保存保留，不自动覆盖坏保存。

## 静态协议与REA

冻结metadata：BankInvestRequest与BankWithdrawRequest无自有字段且继承object；BankWithdrawUseItemRequest另有count:int。Invest/Withdraw Response继承PlayerDeltaResponse，无自有字段。空请求不授予客户端自报金额或余额的权威。

M154911 _OnInvest 0x3f14f48、680/680，body SHA de15fafc2aa5610625796a7f4a2f55d4ba4e7f006e3e5bb062b480be8db600a8；M154902 _OnWithdraw 0x3f1454c、520/520，body SHA ba823d46775ceae9150097e58f2dfeaf6e4dd17abec2203459caa79c150574ce。静态12288字节/26完整种子，包062bf8c8b7082d1d131a7b30d103f0e0575fb607e07b2a417d1c777510d564ed。

REA会话90510公开close、actual exit0/server0，首伪代码52.343秒、第二个0.031秒；观察超时没有重排同一请求。_OnInvest ev_1d7dbc82726fe0c331690f4afba13ad4c1118387729075745dd2785785900b78默认先检查interactable、当前投资状态及额度上限，再构造空BankInvestRequest；_OnWithdraw ev_c9eea1f69d93f7db0d07f9ac04f58b42a2762cd146bb80c8070038711b5ba32d默认经WithdrawPreCheck构造空普通取款请求。两者通过通用发送链，原Hotfix/重叠全局警告保留，不据此声称已知完整业务或真实路由。

静态路由字面量仅找出3个rlv2候选，没有这两路由。两个实际发送方法的全局引用指向metadata usage，但初次按移位索引没有有效候选，改不移位后得到无关ACT_ARCHIVE键，不能把合法ASCII当正确路由。两次诊断均保留，不猜接口名或用它开空成功。

## 社区规则与数据边界

[PRTS首主题投资段落](https://m.prts.wiki/w/傀影与猩红孤钻#本主题下的独特机制与机制调整)本次实际读取：单次存入花一源石锭并增加一余额；最高余额和累计存入分开，奖赏在探索结算后影响后续探索。普通取款逐次费用翻倍、到32封顶，每个商店重新计次；投资故障不阻止已解锁的取款。这是社区观察的有限规则依据，不是官方服务器代码或故障概率；具体阈值/999上限仍同时核对实际导入e915首主题/NORMAL0和开放状态。桌面页抓取超时后读取搜索结果中已观察到的移动页成功，未降低TLS。

## 原生路由观察夹具准备

仅复制已验22用户保存到新D；绑定已有QA20、原探索751ac5ae，不创建探索或招募。该账号原level1/progress0/未完成入口引导，本副本明确复用已验QA21的level50/progress100和六个入口/引导位。其他21完整用户保持，原201输入受保护。bank余额200、奖励keys、商店open/canPut/canWithdraw及cost仅覆盖本进程发出的同步显示，不存入DB；实际bank保存仍是原值。所有rlv2写操作由QA中间层显式409阻止，不能扣款、发奖、购买、移动、退出或开战。这只用于观察银行按钮发出的准确请求，不是自然银行供给、余额来源或交易验收。

v1准备因Settings.save已创建client目录而copytree拒绝，发生在数据库复制/启动前；保留失败副本，v2在自己新建目标内合并已准备的本地客户端目录。v2准备22用户/其他21保持及201保护输入检查通过，业务3bb48495不变；原生会话41151实际connected，后续观察结果如下。

## 本轮实际原生协议与停止审计

资源检查/登录后，本轮QA20确实弹出三项协议；恢复时先实际看seq9图片，用户“确认，现在接受并继续”适用于此刻。seq10勾选、seq12继续，已看勾选和主页两图。此前REQUIREMENTS所述“未再次弹出”是上轮QA21事实，已纠正当前段落；本轮agreement_consents和audit_log改变有明确授权及原因。

从终端已有探索继续，进入原SHOP，不创建新探索/招募/战斗。银行余额200和6件售罄仅显示夹具，存档真实余额仍0。原生投资确认图显示消耗1锭、200→201；seq28只一次真实POST **/rlv2/bankPut**，字段名列表为空。QA显式409后原生显示409连接丢失弹窗，关闭后回登录；同一观察进程重新登录同一探索，以相同夹具一次进入余额提取。取款确认图显示获得1锭、余额200→199；seq45只一次POST **/rlv2/bankWithdraw**、空字段名列表。也被409阻止，实际看图后停止，不反复点击或提供万能成功。

control stop已有停止结果，实际统一执行41151回读exit0、自有index1/ADB/TLS退出。独立verify_protocol.py exit0：41请求中39条200、2条刻意拦截409，无404/500；22完整用户中其他21保持，目标完整rlv2与预备快照相同、局内gold仍6、永久bank仍false/0/空reward。75表核对，只有player_profiles、local_sessions、agreement_consents、sanity_states、audit_log五表改变；所有rlv2表保持。201原输入和业务3bb48495/175文件保持；重新打开Runtime只读后全75表不变。无新交易/发奖/战斗/EXE，不将本次刻意错误弹窗记作正常交易通过。

实际导入首主题gameConst还核到bankCostId=null、bankDrawCount=0、bankDrawLimit=0、bankMaxGold=999/HIGHEST_RECORD。前三者不能据零值宣布普通取款免费/无限或不可取；本轮wire bank.cost=1及canWithdraw=true是明确夹具。须结合具体原生消费者/业务证据继续，不从默认对象推广规则。证据.cache/rogue-bank-protocol-native-20261030-v2/saved-verification-v1.json、requests.jsonl、ack-0010/0012/0028/0045及对应图片；全部原生图片/保存/日志仍仅本地。

本地.cache/rogue-bank-actions-20261030/{rea-bank-actions-v1,mcp-bank-actions-v1,route-literal-candidates-v1.json,global-route-reference-v1.json,global-route-reference-v2.json,prepare_protocol.py}及.cache/rogue-bank-protocol-native-20261030-v2/{prepared.json,prepared-state.json,prepared-users22.json,ack-*.json}保存实际证据。官方代码页、伪代码、存档、认证/日志/图片仅本地，不入Git。

## REA视图消费者与源码推进

在同一冻结metadata/native文件上另取12288字节/44完整种子，包a18e89e0feb71e3d485befbc714cd0cc1790ab22168d50ad8a396100f42db7cf；代码范围0x3f1b000..0x3f1c000及0x4097000..0x4098000。原始函数/伪代码仅本地。会话71712实际exit0/server0、close_binary成功、包保持。刚启动时ask_view因ready尚不存在而拒绝，未入队；等同一活句柄ready后才open。首反编译55秒，45秒观察超时未重排，原ACK正常返回；其余五个方法0.016..0.031秒。保留Hotfix/坏指令/重叠全局及间接调用警告，不以反编译声明消除限制。

- M155048 LoadData ev_743e4bf783d7e1cf0abbf528858ffa46a9611d1016de918c5469b2c7cbd9b143，248/248：绑定Shop.Bank、主题永久Bank及局内gold，再读常量和插件。
- M155050 GetBankInvestStatus ev_d73dfa3276cba6e625c1057c175cae33833e50adf8c6c7f60b82fb949ecc4376，140/140：默认故障状态和新奖励提示分开；未将枚举数字直接加成服务器交易状态。
- M155058 _LoadConstData ev_8e0dcfc1f251f64c342e6318765ae2dfa6052ba8505cff3d737786ab92db4117，当前完整种子：从实际主题gameConst取相关字段，不能据null/零的初始值造跨主题规则。
- M155060 _HasNewBankReward ev_02f4fabf14984032ee71a513d19a4b23f52611af659887b7232f14f3e2a70098：调用已有M33696累计值；循环奖励时比较**恰好等于**unlockGoldCnt，再按reward字典ContainsKey判断缺失。值0仍为已有key。不能用>=重现该提示，也不自动补齐较低奖励。该函数本身未加show/hasBoss/mode限制；调用上下文与授奖权威另论。
- M160870 RL01 CheckWithdrawReachLimit ev_114686ca176572cf9ddb1369f2993040a7e142b233dfa584104da03a439c46c4，120/120；M155052通用委托ev_4f228f85ebc7c32564cb2eb2663284e5d50b29c83fb5a5b0c700eb5795786311。前者Hotfix截断，额外保存完整汇编，后者经插件间接调用；未据伪代码void或零值推断所有模式无限取款。

FirstThemeBankRules新增只读has_new_reward，复用严格快照/实际计数类型/奖励表校验。没有改旧栏位/累计规则的policy或指纹，没有新增路由、存款、取款、授奖、迁移或改变旧保存。新12例与受影响旧21例合计33针对检查通过；覆盖门槛前/恰好/超过、三种奖励、值0的已有键、同门槛多个奖励、峰值/累计分歧、show=false不附加门、null及坏状态拒绝。两文件Ruff/AST/diff通过；旧1316其他检查未受影响不重跑。保留既有Starlette/httpx弃用警告，未修改依赖。

当前源码业务**5f1074098faee13570b7a40184fa1fef0dc88f7d0dedf3966b0d1b5bd9db30d5**/175文件，schema0034/75表。当前源码独立只读打开旧22用户保存，完整users与原快照相同、75表和DB字节保持；5个实际导入奖励逐一核对精确门槛/值0已有key/超过不提示，201保护输入保持。此检查0UI/交易/发奖；本轮原生路由观察用的是此前3bb48495源码，不能写成新增提示逻辑已原生验收。证据.cache/rogue-bank-actions-20261030/{bank-notice-v1.xml,bank-notice-frozen-v1.json,rea-bank-view-v2,mcp-bank-view-v2}。

下一接权威存入/取款账本、与商店购买交错的gold资源回放、防重复和结算后奖励生效；空请求通过现有会话seq/幂等收据区分重传与新一次投资，不能因同为空体把所有后续存款永久折叠成首次操作。未知故障概率、故障发生时是否记入该笔、首次出现概率与完整自然池继续取证，不自动设零或默认开放。完整银行/自然地图供给、其他模式与最终成熟交付仍未完成。


## 本批私有回滚检查点

源ccc91487cf6cdb1326bf56d0ebcb89081519d641，业务5f107409/175；包TerraLocal-rogue-bank-actions-20261030-ccc9148.bundle，2189554字节、SHA256 8fd0957540c090bf3cf46faec9ce867974d151b90b4a9fc5d6091381126d03fb，Git blob fd513f0c35c894f3e13553dfa78a858430b6348d。私有提交b67456f5b775251e77d5b87349fde7d8a31698a9，tree451b09a75d6705ca6983da16f31aa2cb34aae2fb、README acf63302adae82725d24e3810b8315e68137076f。连接器实际回读private/main/tree/完整README通过；192树项中旧190非README项和108813字符完整旧索引保持。514历史路径/2360文本blob扫描无禁止路径/凭据标记。

实际浏览器下载新包，两hash一致；新的D恢复目录512文件/200完整提交、全部源blob/树/历史/Prompt、fsck及干净工作区通过，仅新下载且二次校验过的C临时文件移至D。权威.cache/github-checkpoints/rogue-bank-actions-20261030/upload-verification.json及heartbeat-latest.json。普通Git既有登录的非交互只读探测exit128，未声称codex/development已正常推送。检查点包含新源码/测试与此前原生/REA记录，本完成段晚于包，不重复打包。

失败与恢复：PowerShell追加文档引入的CR换行触发diff空白告警，统一这些新追加换行后diff通过；首次批量读取包分片未区分仍运行会话而终止组合，仅重复了无副作用的只读读取，未上传坏包。后续对24个实际返回句柄逐一回读完成并核总长，GitHub新blob SHA与本地一致；今后保存所有句柄后只续读，不将观察超时当失败。连接器tree/commit/ref初次参数名不匹配均在schema层拒绝，未改ref；修正到tree_elements/base_tree_sha/parent_sha/branch_name后成功。树计数首次把替换README也当新增而断言失败，核实旧191+新包1=192且旧190非README全保持，再用expected_sha保护推进main，未强推。所有旧包/发行物/保存保持。
