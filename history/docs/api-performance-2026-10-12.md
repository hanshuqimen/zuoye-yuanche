# 同步读取、接口性能与实际 EXE 验收（2026-10-11～12）

A09 的已支持编队流程已达到本机 P95 <50 ms 目标。两个生产文件改动，增加七项必要回归；完整 **612 项通过（88.18 秒）**、Ruff 零诊断。实际 EXE 的 TLS、内存、模拟器冷启动/真实主页及两个账号的进程重启快照通过。日志另外发现寻访记录网页 `GET /gacha` 返回一次 501，登记为 A12；**零未知路由与成熟交付尚未通过**。

## 瓶颈与改动

在冻结 18 表和 429 名干员的新测试存档上，以五次预热、每路径 80 样本复现编队 P95 198.952 ms。分层采样中，第二代垃圾回收 22 次共耗时 3,540.494 ms；SQL 执行中位数约 0.506 ms、日志写入约 0.235 ms。直接运行剖析显示每轮完整组装反复加载大量干员/技能 ORM 实体，60 次组装创建 83,460 个实体。

`Context.read_rows()` 在同一事务内显式 flush 后读取列值，每次重新查询当前归属和成员；同步读取避免创建可写 ORM 实体。技能通过账号归属连接查询，包含新增技能而排除其他账号。领域写入继续使用原来的 ORM 路径，事务、提交、回滚和幂等收据规则保持。

列值读取、实体读取和 flush 的边界与 [SQLAlchemy 查询说明](https://docs.sqlalchemy.org/en/20/orm/queryguide/select.html#selecting-individual-attributes) 及 [事务 flush 说明](https://docs.sqlalchemy.org/en/20/orm/session_basics.html#flushing) 对照。没有引入跨请求存档缓存或修改垃圾回收设置；减少对象分配的效果由下面的实际测量证明。

## 测量

全部采用最近秩法计算 P95。源程序的 TestClient 和实际 EXE 的本机、证书验证 TLS 分别测量；测试期间模拟器关闭，没有并发 pytest 或构建负载。

| 场景 | 每路径样本 | syncData P95 | 编队 P95 |
|---|---:|---:|---:|
| 修改前，空编队 | 80 | 195.732 ms | 198.952 ms |
| 修改后，空编队 | 80 | 31.734 ms | 42.111 ms |
| 修改后，空编队扩展 | 300 | 31.482 ms | 42.761 ms |
| 修改后，12 人并交替切换默认技能 | 300 | 36.520 ms | 47.170 ms |
| 实际 EXE/TLS，12 人并交替切换默认技能 | 300 | 31.378 ms | 46.246 ms |

80 样本修改后第二代回收由 22 次降为四次。仍有少数约 200 ms 尖峰，不能声称最大延迟低于 50 ms。实际 EXE 的空载服务进程工作集 101.28 MiB、已加载工作集 291.18 MiB、峰值 296.56 MiB；空载未启动 Tk 窗口。这些测量不能外推全部普通接口、其他电脑、局域网或多账号并发负载。

## 一致性与发行程序

七项新增回归包含事务内未显式提交的干员/技能/货币变更、插入与删除、数值字段、账号隔离及组装 flush 后异常回滚。167 项寻访、养成、编队、语音及结算相关检查通过；完整 612 项通过，有一条既有 Starlette/httpx 弃用提示。

新的真实存档副本有 42 名干员、43 条寻访历史。列值快照与实体快照一致；八次并发重试仅增加一次 revision，全部返回同一收据。错误操作在组装 flush 后回滚，备份恢复和重启完整同步一致，九张玩法表及数据库完整性保持。

独立开发包为 `dist/releases/20261011T121804.616197Z-3f5f482a/TerraLocal/TerraLocal.exe`，SHA-256 `765c16df2ce58b82975ae7a30c3223a3304bdcc9c8fddcccee74f7547b8f04cd`，1,079 文件指纹通过；没有附带客户端、官方资源或存档。实际 TLS 指标如上，真实 SDK/U8/登录/同步返回 200，客户端显示主页。进程重启后 Doctor 和 429 干员账号的完整同步一致，有效 SDK 复用，九张玩法表保持。

原验收进程在等待原生确认期间结束，未生成完成记录；先确认句柄消失、EXE 进程不存在、模拟器关闭，再使用同一个已核对 EXE 和保留的测试副本接续原生与重启检查。原性能/内存已完成记录保留，未重复测量或声称中断期间已完成原生验收。最早的性能脚本也曾漏应用中间增量，已修正后另建副本重测；该次失败没有发布指标。

相对 A08 清单，生产 `context.py`、`sync.py` 有变更，新增 `test_sync_projection.py`，零删除；自有代码/测试共 164 文件（生产 87、工具 27、测试 50）。清单 SHA-256 `6b52e05c4c75c9a00ebb0249fc98bb8b4aa2b930fb0f57bab004fafce8fc90e5`。32 份既有输入指纹保持。验收服务和两个模拟器停止；正式存档与旧发行程序未替换。

## A12 与剩余范围

复核 659 条请求记录发现一次 `GET /gacha?pool_id=…`，主机 `ak-webview.hypergryph.com`，返回 501。官方 [寻访记录页面](https://ak-webview.hypergryph.com/gacha) 的公开资源表明它调用客户端 `getPlayerToken` 认证桥，再查询 `/api/gacha/cate` 和 `/api/gacha/history`。这与已支持的 `POST /gacha/getPoolDetail` 不同，不能用静态干员名单充当个人抽取记录。凭据阶段及完整记录查询仍待实现和原生验证。

累计已确认 A01–A12，前 11 项按各自验证范围修复，A12 尚未修复；其他寻访类型、主要商店、完整任务、基建、社交、活动与高级模式仍有缺口。管理/启动窗口视觉、Golden Playthrough、完整断网、两小时游玩及 HarmonyOS 尚未验收。网页权限界面显示 Allow，但浏览器工具此前仍返回保存的阻止项，未采用其他方式获取被阻止的管理界面。

证据：[完成记录](../.cache/api-performance-2026-10-11/verification.json)、[原生/EXE](../.cache/api-performance-2026-10-11/binary-results.json)、[副本一致性](../.cache/api-performance-2026-10-11/integrity.json)、[源清单](../.cache/api-performance-2026-10-11/source-inventory.json)、[请求汇总](../.cache/api-performance-2026-10-11/binary-routes.json)、[官方网页资源指纹](../.cache/api-performance-2026-10-11/official-gacha/asset-receipts.json)。
