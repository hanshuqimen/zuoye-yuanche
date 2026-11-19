# 上游研究记录

研究日期：2026-10-07。版本支持必须以自有客户端复核；不能将上游 README 的“完成”视为本项目验收。

| 来源 | 已核查依据与借鉴 | TerraLocal 的处理 |
|---|---|---|
| [OpenDoctoratePy-EX-Public](https://github.com/jiellll1219/OpenDoctoratePy-EX-Public) | 2026-02-22 归档；GPL-3.0。读取 README、server/app.py、account.py、quest.py、user.py、config/prod.py、config/config.json。历史 CN 配置是 2.7.01 / V070，独立路由涵盖账号、公告、编队、基建、商店和活动。quest/battleFinish 返回固定空奖励，不能作为真实结算实现。部分公告/配置仍请求官服。 | 仅用作历史协议线索；不复制实现，不继承其固定战斗 ID、延迟 JSON 写入、官服转发或万能默认路由。对实际 2.7.71 建立 fixtures。 |
| [OpenDoctoratePy](https://github.com/baiqilingnai/OpenDoctoratePy) | cn-dev，CN TapTap；提供雷电/MuMu、Frida 启动与 syncData 模板。_.js 包含混淆打包内容，不能审计为可维护的兼容层。 | 自有客户端按指纹选取可读辅助脚本，运行时服务器与录包解耦。 |
| [DoctoratePy](https://github.com/nonobject14514/DoctoratePy) | 早期 CN TapTap 本地服务，mitmproxy、Frida 和四个命令窗口组成运行流程。 | 参考历史协议；最终启动器统一管理服务与诊断。 |
| [Darknights-server](https://github.com/LewisGet/__Darknights-server) | nginx-ver，CN；代理 → Nginx → Bottle → MongoDB；README 明确大量系统未实现。 | 保留协议/领域/持久化分层，使用 SQLite 简化本地部署。 |
| [KCN_ArknightsServer](https://github.com/JDDKCN/KCN_ArknightsServer) | C# GUI，一键启动、IP 配置、GM。README 要求旧版客户端和手机代理；AGPL-3.0。 | 借鉴启动诊断和本地地址展示；不继承公网开放建议、任意验证码或数据库依赖。 |
| [LocalArknights](https://github.com/sanhaiwangxing/LocalArknights) | MIT；1.6.01 / 2021-11 资源；覆盖好友、助战、招募、寻访、养成、掉落、部分基建。 | 研究持久化系统之间的关联，不能把旧版本接口当作 2.7.71 标准。 |
| [Arknights-RE](https://github.com/djpadbit/Arknights-RE) | 自有 Android 模拟器 MITM、Frida、FlatBuffers、战斗数据和遥测研究；部分地址只适用于 24.2.21，示例包含官服自动操作。 | 不运行官服自动操作脚本；只验证本地测试客户端所需的编码和解码。 |
| [rhine](https://github.com/kyoukaya/rhine) | BSD-3-Clause；模块化流量处理和状态镜像。JSON delta 包含 modified/deleted，不能只模拟完整 syncData。 | 建立独立协议工具及 delta 一致性回归测试。 |
| [ArkPRTS](https://github.com/ashleney/ArkPRTS) | GPL-3.0；Pydantic 类型与 raw 数据映射、CN/Bili/国际服差异。models/data.py 明确部分 IDK 字段仅为推测，并非完整用户模型。 | 不将 wrapper 安装为官服调用依赖；分别验证别名、空值、遗漏字段和版本行为。 |
| [ArknightsGameData](https://github.com/Kengxxiao/ArknightsGameData) | JSON 表来源，README 说明部分数据借助 FBS 解析。 | 不 vendor 完整数据；本地导入并记录来源、hash、版本和 schema。 |
| [OpenArknightsFBS](https://github.com/MooncellWiki/OpenArknightsFBS) | FBS 定义、flatc 转 JSON；README 从 CN 2.0.01 开始，文档并未证明所有当前 schema 兼容。 | FBS 与 GameData 单独版本化，转换后校验引用和字段。 |
| [TerraPS](https://github.com/DoctorateRS/TerraPS) | Rust，多 crate；README 自述 semi-functional；肉鸽节点/战斗、生息演算、保全派驻有探索，Windows 构建说明未完成。 | 借鉴运行状态模型，不声称全部模式已完成。 |
| [mitmproxy 官方文档](https://docs.mitmproxy.org/stable/concepts/certificates/) | TLS 信任、Android 系统 CA 和 emulator image 差异。 | 研究工具只处理指定自有实例与游戏域名，离线服务器不依赖代理转发。 |

网络环境：公开 GitHub API 曾返回限流 403；已通过公开页面和原始文件完成上述核查。

2026-10-19补查：[Arkdays冻结源码](https://github.com/Shiiyuko/Arkdays/blob/8ccded0896fc3493ceb0d9dbfd4e10d0b2b51b5e/src/main/java/com/hypergryph/arknights/game/campaignV2.java)按原始击杀硬编码奖励与25理智返还档位，没有匹配本项目冻结版本的周收入账本；不能代替已观察到camp_01的20/14理智规则或证明精确收益。[Darknights所查battle.py](https://github.com/LewisGet/__Darknights-server/blob/729115615df4af3a0e79527e4902654c7314ce2d/core/battle.py)为普通quest样例响应，不提供所需Campaign结算依据。两者仅在本地缓存只读研究，没有执行或复制到业务代码；文件摘要和范围为`.cache/campaign-reward-research-20261019/bounded-reference-findings.json`。不能以参考项目有路由就标记本项目完整玩法完成。
源代码引用使用文件 URL，并在后续协议记录中绑定实际来源 revision / 文件 digest。

2026-10-12：按用户建议实际安装并使用 [REA](https://github.com/morluto/rea) CLI 6.4.0，在 D 盘分析官版 APK 和公开寻访网页资源。Android package/class/method 操作成功，网页静态图有明确语义覆盖缺口；局部 native 调用链由既有离线工具交叉核对。原生隔离页面证实寻访认证桥传递本地 U8 令牌，无需更改 SDKv2。详细 Evidence ID、来源、未知分支及历史接口修复进度见 [REA 调查](rea-investigation-2026-10-12.md)。工具分析和完整逆向分别记录。

2026-10-08 按用户指示优先分析本地官服 APK。已建立完整 IL2CPP 声明索引、泛型注册映射、
协议类型候选和选定函数的调用路径；指纹、覆盖范围及未解决问题见 [客户端分析记录](client-analysis.md)。
