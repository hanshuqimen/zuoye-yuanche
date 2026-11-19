# 首主题休整与进阶券：静态规则和客户端合同

2026-10-25。按用户效率安排继续下一个功能，不恢复剿灭，不重复旧关。此次没有启动模拟器、战斗或改写游戏保存。**完成静态筛选适配，未完成可玩的休整/晋升**；不以数据条数或检查数量替代原生验收。

## 源码与数据

新增`terralocal/server/gamedata/rogue_upgrades.py`和惰性`GameData.rogue_upgrades`。只在显式使用该目录时加载；既有普通招募和旧保存不因新增表约束而改变。

范围固定为CN Android2.7.71、首主题`rogue_1`，实际导入19表指纹`e915675d8d8a1cc97df8fa46eed27ef1bdaa9d1b0fdb07461dcabda36271ae29`。首主题当前是归档主题；此目录不决定开放时间、模式资格、票券归属或玩法入口。

- 一次覆盖实际全部10种进阶券：任意、五星及以下、八职业。逐项核对物品引用/type、原始profession/rarity枚举及展开列表；缺失、重复、混合类型、未知类别及不一致拒绝加载，不作默认替代。
- 适配两个明确养成上限：upgrade0为精一/技能7/专精0，upgrade1为精二/技能7/专精3。是上限，不是自动给角色满级或专精。
- `matches_definition`只判断静态职业/星级成员关系；支持当前表的字符串稀有度及已有GameData的0..5整数表示，拒绝bool/浮点/越界。**不能直接当作可晋升资格**。
- 不可变票券/上限和独立筛选集合；原始对象后续变化不修改目录。目录摘要包含导入数据指纹、原始票券及上限。
- 没有增加HTTP路由、发券、扣券、晋升、场景效果或GM入口；没有数据库迁移或新EXE。

23项新针对检查通过，Ruff通过，已有Starlette弃用警告保留。覆盖10券×8职业×6星级矩阵以及错误规则、输入和不可变性；不是480次原生游玩。冻结导入目录完整校验后也实际加载通过，目录摘要`017b1d3112e0f5f1b6c3a42b268b3e396153ae4fb97731393cd99d4dce1ffc06`。可获取角色目录中的静态匹配429/五星以下292，**不表示这些角色都拥有、可晋升或已经原生消费**。原149项为此前跨层业务372c0a91的通过基线，本轮不为记录重跑，不冒称验证新增玩法。

## 本轮REA取得的默认调用链

沿此前节点点击→确认→焦点节点继续，补齐冻结原始文件的真实映射页，不读取新Android代码页/堆/认证。代码只供本地分析，不入Git；静态默认分支不是完整热更新/官方服务器实现。

| 方法 | 实际证据 | 当前能支持的结论 |
| --- | --- | --- |
| M151103 `_OnSendConfirmRequest` | ev_f2442afe0238989385ab964af4a0e65364b6659ed9cb5ebf82ba3a70aae76685 | `CanMoveToDirectly`通过后，非定制节点交给M151104；定制节点为回调。 |
| M151104 `_TrySendConfirmRequestImpl` | ev_8631c6fd10a80838498a5f4b0f16bf2a95a00bffbe5d0c78e9f031890ee5fa8b | 默认插件未截获时委托M151106。 |
| M151106 `_OnSendConfirmRequestImpl` | ev_126db34e1f716d951c9a31ad039130b2d09ea52a4991aa5b3995437eef646066 | 构造`RoguelikeMoveToRequest`和`RoguelikeNodePosition`，由节点坐标赋请求。不能仅凭类名再造休整URL。 |
| M153829 `ConsumeRecruitUpgradeTicket` | ev_a2247adc01aaac4eacb7fd9361aa0811cdb0038a246181501dc0ce93eb43ed1d | 默认通过票券索引查现有记录/类型，非负option构造`RoguelikeRecruitCharRequest`、填写ticketIndex及optionId字符串；负值构造`RoguelikeCloseRecruitCharRequest`。没有单独发现晋升请求类。 |
| M153900 结果回调 | ev_aa13d3178fe4a84671028b1c9f2241ee8b8a7a5b8f0dc4f9177369b8fa115f23 | 在分支条件成立时传响应chars给`_UpdateGacha`。不据此推断所有返回标志取值。 |
| M153901 完成回调 | ev_97c2db545da1b74af7808570bbdfd410e5fe3dbe7cbf989c3ef9639608547bda | 委托已保存完成回调；不增加业务结论。 |

普通节点两页样本SHA`8f497fbbc424cafb73c2219692a1fa633653d9f2d4cd610e9c3c982b51c34534`；进阶请求两页样本SHA`5aec4d03402a9c967e89c715b3e59efe9fffb57163e0464574a06f706ac8f8f2`，37个完整解码方法种子。首次进阶反编译57.703秒，同一提供器再查询0.047/0.016秒，后续使用这种会话复用减少开销。种子名称是冻结元数据索引赋名，不当作Ghidra独立发现。重叠全局、Hotfix路径bad-instruction和间接跳转限制全部保留。

## 失败、会话退出与边界

- 本轮第一次方法查询联表误用`m.type_id`，实际列为`owner`；只读SQL失败，无输出文件/DB写入，按实际schema纠正。
- 首次进阶样本计划还包括M154585 `OnFinishSelect`。其静态840字节只线性解码404字节，在`0x3efd000`页边界停止；前置守卫拒绝启动提供器。保留原样本，不强行种为完整函数，不根据此结果声称代码加密、URL或晋升规则。第二样本只接纳完整解码的M153829及回调所在页；该候选生成失败不是游戏运行错误。
- 普通节点87289与进阶61956原exec均实际退出0；REA stdio服务退出0、目标文件摘要保持。两个`close_binary`都返回`cleanup_incomplete`，原因是清理时观察到`[java]`而非预期完整命令身份；**退出0不能抹掉这个工具层失败**。随后只读核对其报告Linux PID486/480均已不存在，未手动递归清理资源目录；快照/诊断保留。不能描述为提供器清理全部成功。
- 进阶查询控制52510的45秒观察到期后返回pending，分析实际仍运行；回读相同会话ACK得到成功，没有重新排队或重启。

## 下一实现点

本轮已从冻结索引确认真实嵌套类型：CurrentData.Inventory.recruit为索引到Recruit的字典；Recruit.list/result为RecruitChar数组/对象，RecruitChar含upgradePhase、upgradeLimited、population、isUpgrade、troopInstId及charBuff。只证明字段类型，不推导服务器取值。下一步核对进阶前后upgradePhase、upgradeLimited、isUpgrade、troopInstId、角色等级技能及资格。加入独立版本化晋升记录，按开战时点构造历史编队，保留原招募候选和旧battle快照；不能直接覆盖`RogueRecruitOption.character`。随后把休整四项选择、发券/候选/晋升/放弃/离开及跨层待办完整接入，再一次新代表原生验收。正式节点供给权重仍未知；显式服务器方案与官方分布继续分别记录。

本地证据入口：`.cache/rogue-rest-20261025/upgrade-rules-junit.xml`、`upgrade-rules-frozen-proof.json`、`mcp-focus-wide/`、`mcp-promotion/`、`rea-promotion-static/`失败样本与`rea-promotion-static-v2/`完整样本。客户端和所有本地分析字节不提交。

## 检查点与恢复

2026-10-25进阶静态规则检查点6ff8666已完成私有远程回读/新D恢复：402自有文件/109源码提交/404历史路径/1389blob已扫描，禁止路径/凭据标记0；包1469451字节/SHA4cfb763b0169c5e20fa27d93c3107b426b42924b8447c917bbe7139302467925。连接器上传/索引2eec063a从旧33f17c14前进，159非README旧项及旧索引完整文本保留，当前161根项。精确提交网页raw下载实际完成，正常浏览器下载先落C盘、立即D盘复制；新D恢复HEAD/全部402源Gitblob/109历史/Prompt/fsck/干净工作区相等。第一次本地恢复直接比工作树字节忽略Windows CRLF导致断言失败；保留原包/目录，续验Gitblob及规范化工作区通过，没有重建或抹掉失败。连接器二进制读取不可用（unsupported binary read），网页完成下载替代；README元数据响应已是文本，首次当JSON解析失败后按实物处理，未更改权限/提取凭据。源码范围是十券静态约束、23新检查、REA默认合同；休整/晋升实际玩法及成熟成品仍未完成。完整本地权威`.cache/github-checkpoints/rogue-upgrade-rules-20261025/{upload-verification.json,checkpoint-web-proof.json,restored-remote-6ff8666}`与heartbeat-latest。之后这条记录不在6ff源包内，不重复生成仅记录包。
