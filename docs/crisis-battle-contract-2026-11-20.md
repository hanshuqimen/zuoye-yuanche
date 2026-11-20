# 危机合约V2：战斗请求与消费者

信息源和0038存档已实现并公开，范围见[信息阶段](crisis-information-2026-11-20.md)。本页记录后续开战/结算研究，不能当作战斗已可玩或完整原生验收。

## 开战路径与数据来源

复用同一冻结2.7.71的两批已保存代码页，没有新启动模拟器、读取活动Hotfix或认证。REA实际查询8个元数据界定的方法范围，合计3,384字节；最初两个入口496字节经过完整线性解码。其余三个辅助getter的Hotfix分支出现bad instruction，保留部分结果，只引用默认字段读取。容器12,288字节，SHA-256 `31466e2e1b167214e260661685d777cc8118eff9709340e2d9ff2458d21e6f2c`。

EventOnStartBattleClick的默认路径进入_TryJumpToCrisisSquadPage，再调用已核CrisisV2StartServiceConfig构造函数。结合字段偏移，参数为当前地图ID及GetSelectedRuneSlotList的结果。后者遍历选择集合，只把slotType为NORMAL的槽位写入请求；节点ID与实际符文ID不能混用。请求声明的squad/assistFriend及mapId/runeSlots字段未发现直接字段属性别名，用已知current/nst字段作为属性范围阳性对照；此结论不覆盖活动Hotfix或未核类级转换器。

GenerateBattleStageInfo从m_mapStageData构造关卡值类型，复制stageId、levelId、code、name和loadingPicId，其他字段保持该默认构造中的零值。它不是通过普通stage_table查询关卡。实际独立14457902包首季五张地图的stageId均不在普通stage_table，故不能把现有普通主线start服务直接套上新路由。此观察不单独证明官方理智、奖励或开放政策。

GetPackedRuneData与请求槽位过滤是两段处理：遍历选择节点，经节点runeId查runeDataMap，再读取packedRune；缺失/空值会跳过。首季五图的148个NORMAL节点均有匹配packedRune，其他本批节点没有匹配符文。这是该导入版本五图的实际覆盖，不推广为所有赛季和节点类型的规则。后续战斗会话需要绑定地图、规则指纹和接纳的槽位，并区分槽位、符文及其效果对象。

本地证据：`.cache/crisis-20261119/battle-inventory-v1.json`、`battle-callee-binding-v1.json`、`battle-analysis-methods-v1.json`、`battle-field-attribute-ranges-v1.json`、`battle-field-alias-positive-control-v1.json`及`battle-stage-source-projection-v1.json`。原始代码页、REA输出及第三方工具仅本地保存。

## 关闭与工作区路径问题

开战会话的public close返回cleanup_incomplete：关闭竞态时Java命令被观察为`[java]`，工具没有据此强杀。控制器与WSL子进程实际退出0，随后实际读取/proc与两个被报告目录，均已不存在；无需手动删除或按旧PID杀进程。快照、错误、原始脚本及复核均保留，不能把process exit 0写成public close成功。

进一步发现长运行目录令REA把Unix socket回退到WSL `/tmp`，不符合用户全部新增文件留在项目的要求。改用项目内短且无点前缀的tools/local/rea-tmp后，当前Windows文件系统又返回Unix socket Operation not supported；四次实际分析失败，未得到相应伪代码。尚未开始的队列项已保留并跳过，当前调用完成后public status/close成功、进程退出0。失败现场为mcp-finish-v1，没有改写冻结输入或补造分析成功。

本地工具已保留原GhidraProviderClient.js，仅选择REA原本已有的authenticated-loopback-tcp分支，绑定127.0.0.1随机端口；不改变认证、token、访问权限或游戏端口。工具备份及双指纹在rea-workspace-transport-v1/，第三方工具及原件不进入MIT仓库。自有工具`tools/research/configure_rea_loopback.py`默认只检查，`--apply`只接纳已验证文件指纹、保存原件后原子替换；未知版本拒绝，已有配置不重复写入。实际运行`--apply`返回configured=true、changed=false，Ruff通过。会话仍须把TMPDIR/TEMP/TMP明确设为项目内无点前缀的tools/local/rea-tmp，不能把`.cache/tmp`当作Ghidra项目根。此工具只配置研究环境，不是游戏运行依赖。

## 结算默认消费者结果及剩余范围

修复传输后，mcp-finish-v2在同一输入上先取得一个成功代表，再分析其余四方法。五项均返回非空伪代码且没有bad instruction警告，共2,432字节；16,384字节容器SHA-256 `1b62dc8ac3b433362bd3cc75c215b74cdf5d8e9d6be0e40628680c241b3f60c2`。仅冻结APK默认实现，未补加载等价或活动Hotfix证明。

- SetBattleLog把输入直接写到请求battleLog字段，没有在这个setter中进行另一层编码。它不证明调用方传入日志的内部格式，完整finish编码仍须核对。
- _LoadCommentsByResponse区分commentNew与commentOld，分别带“新增”与“已有”的标志，通过该地图commentDataMap构造展示；未知/空ID跳过。两个列表都空不触发评论字典加载，不把空样本当作所有玩法无评论。
- _LoadRuneDataByResponse遍历响应runeIds并交给符文项模型，需要匹配地图detail及对应战斗服务配置。这里不能用普通槽位ID填充runeIds，也不能据此推定runeCount应是六个零。

public status成功。public close再次遇到Java退出身份竞态，故控制器明确退出1，completion记录底层子进程退出0及输入保持；随后实际/proc/488、报告运行目录和两个Windows PID均不存在，无手动强杀/删除。没有socketRoot或/tmp回退，运行目录及TCP endpoint均在项目内。端口号没有另行保存，不声称做了独立端口探测。错误、快照、cleanup-revalidated.json及成功方法回执全部保留，不能把成功分析与关闭警告合并成全流程无错误。

证据`finish-analysis-summary-v2.json`、`finish-consumer-fields-v2.json`及`mcp-finish-v2/`。FinishView字段索引仍有1684300xxx异常偏移，不根据这些值强行给对象命名；地图detail的commentDataMap偏移有正常声明与实际读取对应。主响应/地图/编队加载方法的APK字节仍受保护，scoreRecord/scoreCurrent/isNewRecord/runeCount/结果枚举及奖励解锁的完整合同继续未完成。下一补这些关键消费者的受控加载依据，再接事务性开战与结算；本批没有新增成功占位路由或原生游玩。
