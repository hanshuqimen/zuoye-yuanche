# 单次肉鸽快照的重复验证开销

2026-11-07 私有检查点已完成：源1b38b93f5263650e11e58f3e5253afebf9f1fcbb/业务cf8dac8c→private91c4cc85e6dcbf111bf2f43ba65f548e35ddacac，父5c062436/tree7ab017e5e64b281e3acfa11256ad9c45b6ff5fb2。2549463字节，SHA256 a8f89229e7cd42f85899ffc39018bf8309dd28d4dc089c55160674e4d9eaf587、blob915b6f234d06752b1a3f60d5c0ffed5ea87de7b4。实际浏览器Download事件回读双hash/新D566文件253完整提交与全tree/blob/Prompt/fsck/干净恢复相同。568历史路径2874UTF8 blob扫描无禁止路径/凭据标记；215旧非README项和118645字符完整旧索引含原CRLF保持，新tree218。普通Git禁交互只读probe128/1.435秒无ref，不称源码分支直推；连接器expected_sha/force=false/private/ref/commit/tree/完整README/note回读一致，浏览器下载后立即completion_summary。仅本次新C临时下载双hash后移D，不读凭据/扩权，旧备份/存档/发行物/失败保持。权威.cache/github-checkpoints/heartbeat-latest.json及rogue-read-scope-20261107/upload-verification.json，actualexit0。包内含89检查/真实23-77恢复、原生交易与短触待核、性能小样本及普通API目标未达；完成文字晚于包，不为文字另打重复bundle。完整目标ACTIVE未完成。

完整目标ACTIVE未完成。本轮从生命交易原生记录中发现秒级轮询后，定点优化已有存档读取；不重新游玩、修改正式保存、重复验旧关或取消剿灭。生命交易结果及输入触达待核见[本次事件报告](roguelike-health-trades-2026-11-07.md)。

## 定位与修复范围

原生记录syncData单样914.507ms、syncStatus1876.142ms、syncPushMessage最大6198.683ms。独立D副本在无模拟器输入下重现：单次SyncDataAssembler组装的cProfile有56次rogue_runs.validated，两个history_in_session反复遍历同一历史；collection、band记录和variant前缀分别再次验证相同探索。轮询/刷新组装before/after两份完整快照，累计112次。cProfile放大绝对耗时，因此耗时对照使用不带profile的独立样本。

新增rogue_reads.py作用域只包裹rogue_topics.snapshot的一次调用，成功验证的探索children/progress和完整结算history/deployments在该范围内复用。仍完整核对每个涉及的探索及其拥有者/来源/因果账本；不保存客户端响应，不跨请求、快照、Context、事务或恢复保留。未完成或失败验证不写入复用表，异常后finally删除作用域并移除Session监听。待flush ORM变动先flush；before_flush、Session非SELECT执行和事务结束均清除条目。作用域只用于投影读取，不能包住域动作或跨原始connection写入；现有投影没有这种写入。

rogue_runs.validated只有在该范围内复用已通过结果，progress_out仍逐调用交付；history_in_session复用完整已验证历史时仍补deployment_history_out。scope外原写流程、启动preflight、事务提交、幂等、schema0036/77和响应字段未改。新增188个Python文件中的第188个，不添加数据表或保存版本。业务摘要cf8dac8c8c705a161b012534c9c71c2646c6ede5eccb9631997454867d805794。

## 检查与实际保存

新模块最终6项覆盖有已结算探索的有/无作用域投影完全一致、同一Context新快照重新验证、旧记录随后损坏仍拒绝、不改保存；未flush ORM、已flush ORM、Core UPDATE、Core DELETE各在复用后造成非法记录时仍拒绝且事务回滚；失败作用域清理后不能掩盖后续损坏。第一版5项通过后补未flush反例并修正facts先flush，旧XML/read-scope-v1保留。

相关6模块89不同检查通过，包含新6项、轮询鉴权/理智/邮件、图鉴坏来源、结算原子性/重试/并发/恢复、附加条件和生命交易。58203实际exit0/89过、5Ruff通过；旧Starlette httpx弃用警告保留。不将此称全游戏零bug，也不累加第一版5项。

真实冻结19表e915675d…71ae29、QA23完成生命交易后的完整23用户与优化前native-save-compatibility-v1逐字段一致，全部77表除独立QA登录会话外保持。三个真实HTTP路由syncData/syncPushMessage/syncStatus均200；最终23完整用户/77表真BackupService备份恢复、Runtime重启及新D恢复一致。原生DB/settings字节保持，无新Android输入/战斗/EXE。23421实际exit0，证据read-scope-actual-v1/{verification.json,profiles.json,restored-new-d}，原生存档不回写。

## 有界测量与仍未达成的目标

同一原生最终保存的不同新D副本、每项预热一次后5次串行端点函数调用；不含HTTP序列化/TLS/网络/客户端解码，不是两小时负载或整体P95证明。

| 项目 | 修改前中位数 ms | 修改后中位数 ms | 修改后5样本范围 ms |
| --- | ---: | ---: | ---: |
| 完整组装 | 809.817 | 93.496 | 89.659–104.641 |
| syncData | 743.309 | 113.036 | 107.682–120.477 |
| syncPushMessage | 1531.190 | 195.534 | 190.143–398.757 |
| syncStatus | 1540.905 | 193.395 | 185.385–390.484 |

单组装完整run校验56→5，轮询/刷新112→10。一次投影仍须验证5条真实探索；双快照及其他链验证、查询仍有成本。普通API P95<50ms尚未达，syncData样本低于300ms但样本量/测量范围不足以标整体P95达标；内存、长历史规模、多账号并发和原生响应体体验没有本轮新验。未改变硬件/TLS/离线配置掩盖结果，也不删账本或跳过完整性验证。下一继续针对真实慢链做有依据的优化和功能开发，不重打关卡。

## 失败与证据边界

准备poll-profile-v1因settings.save已建profiles而copytree目录存在失败，尚未执行profile；保留目录。v2修正后完成组装/syncData并保存prof，随后按app.routes取直接端点遇KeyError；该版本不证明push/status已测。v3从实际push/status.router闭包取函数，58039实际exit0，两项各5样本和prof，原DB字节保持。后续read-scope-actual-v1四项完整，三个HTTP与保存恢复也独立通过。所有脚本、prof、官方数据、DB、原生图/日志只存D本地，不入Git；自有模块/测试与报告可入检查点。
