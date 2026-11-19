# 银行条件图鉴进度与结算资格分离

上一轮为进展：真实奖赏行商资格、54不同检查及私有e8f489e完整回读/新D恢复已完成。本轮继续完整目标，不重复旧关/存取/购买。

## 复用的REA证据

从实际保留工件重新核对，不重复已完成逆向：M154269 TryGetItemUnlockProgress ev_51fe43837638e7c7c4f54e9cf205d04410468635a2e7478c6e8c40c4502b62af，artifact ccd916a9、伪代码2567fbc7，完整switch的RELIC分支读取collect.relic.progress，长度恰2才取当前/目标。M194808 _GenerateRootItems ev_0e573a5ff9e7b5ecdae13c25500577f45a8819e8045f365a71a1d242bda6e774，artifact49266397、伪代码bb2dfead，分别读取state，0锁定/2计入获得数；并非从进度是否满推导state。两个工件/伪代码全hash、原ACK无错误、原server exit0及索引30c555d4重新核对。Hotfix/全局重叠/类型传播限制保留，不称完整官方服务端判定。证据.cache/rogue-bank-collection-20261031/rea-reuse-evidence.json；本轮未新启REA或读堆/认证。

匹配数据仍e915675d/a550f5e/v077/client_verified=false，冻结CN2.7.71/V070；首主题NORMAL/0银行链来源及结算后后续探索规则见[行商资格报告](roguelike-bank-item-eligibility-2026-10-31.md)。本地规范投影基于已恢复客户端字段和已核银行来源，不声称来自官服报文。

## 实现

新增独立PROJECTION_POLICY rogue1-replayed-bank-archive-progress-v1，不改变既有绑定/报价摘要。BankProgress分别保存current/target/unlocked/known：可信钱包的最高历史余额按100/325目标饱和显示，unlocked只来自完整银行访问/已确认奖赏/独立计分历史验证的reward key；达到门槛但未结算仍state0。未知或无可信钱包不读取旧outer.bank数字/标记来发资格，只投影state0和空进度，避免冒称已知0/325。已真实取得state2继续覆盖，既有获得日志仍是唯一发现来源。

只读银行preflight将其已验证账号结果传给集合预检，且此前完整计分/探索预检仍执行；在线集合在读取银行前独立核计分/探索。两路径一致。已声明奖励ID或匹配条件任一存在就启用严格绑定校验，单改一侧不能静默关闭能力；旧没有声明该能力的QA配置保持范围外。伪state1/2、过量/错误目标/非二元进度、未知计数器的伪数值进度均实时/启动拒绝；无原始outer或旧收据重写、表迁移/新路由。行商仍单独要求不同已结算来源探索，不能因为图鉴标为可获得而回到旧局生成商品。

## 验证与失败

本批11新+46相关=57不同当前检查通过：银行图鉴新11(生命周期1、未知旧来源伪造4、可信计数器伪造4、能力防静默关闭2)，既有银行物品12和银行奖赏/收藏发现34。分批XML related-v1(11通过/1失败)、new-v2(新11+补旧1通过)、related-v3(34通过)，不累加重复项。5相关Python Ruff及182业务AST/diff检查。覆盖最高余额与当前余额分离、已满但未结算锁定、结算delta/重试、只读原outer、响应列表不回写、重启/备份、无来源高余额及零标记不能授予、保存伪造启动前字节保持。

第一批发现新银行预检局部变量rules覆盖原招募规则，导致重启调用错误evaluate；已将新变量独立命名bank_rules，补原失败端到端及新来源检查后通过。未在实际原保存启动失败版本。初次报告/助手路径及Windows字面glob误读均未用于规则；后改为实际文件清单和具体范围。一次工具元数据搜索过宽、部分读取输出截断，仅为定位失败，无功能结论，后续使用已知REA工件复核。

真实新D兼容：23账号中仅账号1–22增加两项银行图鉴规范投影，全部其他完整用户字段与旧基线相同；唯一可信钱包账号22显示q28 state0/[1,325]，r13 state0/[1,100]。账号23已拥有两件，完整sync仍同。77表所有原始行/199保护输入保持；真备份、重启、新D恢复的23完整新投影/77表全部一致。业务513a82485b1c34bd40c7f61e093a97bf354f76a46c354d820fe3d0ceb9096cad/182，0036/77表，投影摘要f3eef63d7d1d68bdfd05d0e25a8ee851ce0a7067c1de46be0b5990eeb6490512。证据.cache/rogue-bank-collection-20261031/actual-compatibility-v1/{verification.json,users23.json,all77-table-hashes.json,working-copy,restored-new-d}。

## 原生与下一步

本阶段目前0Android输入/新战斗/新原生购买。下一用已保留QA22实际银行峰值1的旧商店保存，只读看一次图鉴条件/1比325显示，保留旧账号与资源/硬件/TLS/离线/8秒命令校验；不新建账号、投资或开战，不重打已验证关卡。原生消费尚未验证，不以57检查冒称UI已通过。其后保存私有检查点，继续自然供给来源；原生攻速/完整注册、自然图与随机概率、其他模式/管理/Golden/断网长时/性能/Harmony/成熟EXE及完整目标均未完成。


2026-10-31银行图鉴原生代表通过：源4896e12/业务513a8248，用真实QA22峰值1、余额0的旧商店探索副本，仅看首页→傀影→猩红珍藏→长生者宝盒→013；实际已看图bank-relic-detail-01显示银行条件(1/100)并锁定。已核r13档案order013；q28 order167同合同已实际数据/接口1比325批量接入，按用户效率要求不再滚动逐件原生。先前“结束保存”措辞指worker结束，实际探索MAP_READY/PENDING SHOP；现明确撤回探索已结束的误述，原探索0d7a7dbd-e357-4178-877b-945bc8181de1完整snapshot保持。仅local_sessions改变，其他全部游戏表/61其他账号表投影/198保护输入保持；26HTTP全200、0RLV2请求、0战斗/购买/存取/结算，新异常/JSON路径/Lua nil均0。启动依次EMULATOR_STARTING/NOT_READY后同会话连接，没有重启；未出现新协议、0接受操作。1677 actualexit0，自有服务/ADB/index1退出、index0保留；当前无待续原生/REA。证据.cache/rogue-bank-collection-20261031/native-witness.json及.cache/rogue-bank-collection-native-20261031-v1/{prepared.json,native-results.json,summary-0023.json,errors-0024.json,bank-relic-detail-01.png}仅本地。此前57检查/真实23用户77表199输入备份恢复仍为同业务版本适用证据，不为本次只读UI重复这些检查。下一先私有检查点，再自然供给来源；实际结算解锁state1的原生消费、攻速/完整注册及完整目标仍未完成，未称零bug或成熟EXE。


2026-10-31银行图鉴私有检查点实际完成：源fc679c05902f2419dfd42ebfdbbd75ecac685e7c/业务513a8248→private2c5ea41af7515e40bbdadfb76fc2490d33f033d4、父e8f489e；2307512字节/SHA256 3972c1ec7f6d925032aff25d648b99297834f98c540560e621c489e00efca6c3，Git blob1ac98c54e52bfe62f468ce6a13a19ff32e11d6f8，tree13d399c218b528a7e4d34d79c9521baf3c546f7c。实际授权浏览器下载双hash、新D540文件218完整历史/Prompt/fsck/干净状态恢复同；旧199非README项及113673字符完整旧索引保持，新树202项。542历史路径2562文本blob扫描无禁止路径/凭据标记；普通Git引用此前只读probe128未分类，不称源码分支直推。26读取块均actualexit0，prepare90568与回读63902实际exit0；只本次新C临时下载双hash后移D，旧文件不动。权威.cache/github-checkpoints/heartbeat-latest.json和rogue-bank-collection-20261031/upload-verification.json。含57不同检查/真实23用户77表199输入及原生013银行条件1/100锁定代表26HTTP200/0RLV2/商店探索不变，原生工件/图片/保存等仅本地。完成文字晚于包，不为补文字重打包。下一正常行商基础资格/自然供给出处，按具体条目/模式/实际版本/当前开放核对，不盲补权重或重复已过原生。完整目标及实际已结算解锁state1的原生消费/攻速/完整注册等剩余范围保持未完成。
