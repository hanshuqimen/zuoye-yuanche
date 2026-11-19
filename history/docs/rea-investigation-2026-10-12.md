# REA 与寻访网页认证调查（2026-10-12）

尚未完整逆向原游戏。IL2CPP 的 299,831 个方法声明索引已核对，但声明、地址、局部反汇编和实际运行是不同证据。本轮按用户建议使用 [morluto/rea](https://github.com/morluto/rea)，补查寻访记录网页与 Android 认证桥；不将工具安装或分析成功称为全部函数及业务已还原。

## 实际使用与范围

REA CLI 6.4.0、Node 24.19.0、npm 11.16.0 和独立的 headless JADX 0.7.1 放在 `tools/local`，缓存、临时文件及新证据放在 D 盘工作区。复用 D 盘 JDK 25；没有修改全局智能体或浏览器权限配置。REA/JADX 是研究工具，服务器运行不依赖它们。

JADX JAR 的 SHA-256 为 `6e5eacf500b64292bfb73c49797c1958f6ee44646e43e868039ae7feb573ff75`，与已安装 REA 的固定发布定义一致，来源为 [上游 0.7.1 发布](https://github.com/1013503897/jadx-headless-mcp/releases/tag/v0.7.1)。本机实际执行了 REA Android 检查与方法反编译，不能据 [上游 Windows 支持说明](https://github.com/morluto/rea/blob/main/docs/android-analysis.md) 直接推断本机已通过。

目标是保留的 CN Android 官服 2.7.71 / 190，以及独立测试实例上的 SDKv2。原始 APK SHA-256 为 `0b79b85383e21a6343283bc6bfd7a9d24eb4134abf901115f757da6a5d50f6db`；SDKv2 为 `f75a9643d2d3fb487e5da082492cb2336bce399cabdc0725a895efd186df2e01`。原实例 index 0 未启动或修改。没有读取官方账号认证资料。

## 证据账本

| 问题 | 实际证据 | 结论与边界 |
|---|---|---|
| 原始 APK 的 Android 声明 | REA `inspect_android_package`，`ev_16ed1721e38c3f72046171cf3b556bbe1c8e3dfae15c16305ec2375eb1b423a6` | 包名及版本匹配；12,865 Java 类、3,688 资源。没有验证 APK 签名、Unity native 库或全部函数行为。 |
| Java 桥成员 | `inspect_android_class`，`ev_3607d0cc2ddd27f20bcb22e7aa7fd70b727e89d60916938caab15f5aedeff267` | `WebViewJsBridge` 有 `postMessage`、`ready`、`getPlayerToken`、`close` 等方法。签名属于本引擎显示格式，不是精确 DEX 描述符。 |
| `getPlayerToken` 函数体 | `inspect_android_method`，`ev_a46346548c9558f5d70e39fd1eda3c2785d1c3bacbb63ee2b3223d096eb3761b` | 读取 `WebViewUserData.UserConfig.token`，非空时回调 JSON 字符串；为空时回调无参数。Java 方法体完整取得，不等于动态调用覆盖完整。 |
| 网页模块与静态语义 | `analyze_javascript_application`，`ev_e2c9307d18dfb46b61e3da157b4643a96ff2a1b187e91668d716444e7604f4ce` | 本地六份文件、三份 JS，483 个模块、2,295 个发现，语法解析失败为 0。公共脚本语义分析耗尽 512 MiB worker 堆，整体图为 partial；保留 1 个应用图及 1,119 个语义未知项。 |
| 保留证据的局部视图 | summary `ev_a87249258d81124c9e3d6183ac0894f6a09a90c1fea0490dd1c84017a4470ab1`；桥模块 `ev_29c24afe10b6ef69f1a43036fc4bc01c8726013b162e8d7e52bf81df20d6fa60`；记录模块 `ev_1ae0b0c848a24292050d0ca1dbd65efba5a6204e5a4b3d724f2f5a313311b985` | 复用完整保存结果，没有为读取显示结果重复生产分析。局部视图仍保留父结果缺口。 |
| `/gacha/history` 图追踪 | `ev_92f311fc70f7833eefae72449da3adea8fcad3237f4e69e9f9dcac82f8329156` | 精确 literal seed 在已取得图中匹配 0。不是“此接口不存在”：原始公开 JS 明确包含 Axios 调用，现有追踪覆盖不能自动建立这条请求关系。 |
| Unity 至 Java 的局部链 | 固定原始 ELF、只读索引和 13 个新局部 ARM64 范围，共 4,948 字节 | 使用既有 Capstone 离线读取，并非 REA native provider 反编译。默认分支取 `m_authStatus.oauth2token`，经 Options、UserData 和 JSON 交给 Java bridge；Lua 热修复分支仍未知。 |
| 本地实际凭据阶段 | 新隔离存档、原生“查询记录”按钮、临时研究页；`native-auth-stage.json` 与截图 | native getter 返回值能通过现有 `authenticate_kind(expected="u8")` 的只读接口，HTTP 200。没有显示或保存凭据值，SDKv2 不需要改动。研究页不是已交付的历史查询页。 |

本轮的 `static-address-body-protected` 是旧索引的保守分类，不能用它判定每段函数体都不可读。这 13 段默认路径可线性解码；仍不能把线性汇编称为完整控制流、完整 native 调用图或所有函数均已恢复。

## 认证与网页协议

公开 [寻访记录页面](https://ak-webview.hypergryph.com/gacha) 及其公开 JS 观察到如下流程：

1. 网页请求游戏桥的 `getPlayerToken`。当前 Android 的接口名为 `HGSDK`，方法为 `postMessage`；回调接收 JSON 字符串。
2. `GET /api/gacha/cate?code=…&poolId=…` 返回 `{code,data,msg}`。分组项包含 `id`、`name`、`active`。
3. `GET /api/gacha/history?code=…&category=…` 返回 `{code,data:{list,hasMore},msg}`。
4. 下一页传最后一项的 `gachaTs` 与 `pos`。记录显示 `poolName`、`charName`、`rarity`、`isNew`；`gachaTs` 按毫秒解析，`pos` 对网页为不透明值。

`ready` 消息用于结束 native 业务加载遮罩，返回游戏使用 `close`。只查询记录不能使用万能成功响应，也不能以池内概率名单替代持久化抽取结果。

静态默认分支为 `AuthStatus.oauth2token → Options.token → UserData.token → JSON → WebViewUserData.token → getPlayerToken`；本地实际认证证明该 SDKv2 配置对应 U8 阶段。记录接口因此严格接受有效 U8 会话；游戏写接口继续要求自己的 game 会话。不能为兼容网页放宽所有认证阶段。

## 修复状态与待验证项

生产代码已增加只读记录服务、两个认证查询接口及原版资源加载器；记录来自 `gacha_history`，排除 `RECRUIT`，按账号与分组过滤。时间/位置共同分页，十连中相同时间的多条记录不会只因时间相同被漏掉。首次获得和稀有度使用已经保存的值。临时自制页面已从生产代码移除。

自制页面先在独立源码副本上验证桥与接口，不能计为最终视觉。随后固定原版 HTML、脚本、样式、图片与字体资源，四个可视脚本保留原字节；两份 CSS 只改资源路径，HTML 只移除遥测并改资源路径，保存在本地客户端目录，不进入 Git 或服务器发行包。源码与新 EXE 实际显示原版页面，两套客户端本机字体服务返回 200 并核对文件指纹；限定空分组、关闭返回、重启和前后翻页通过。详见 [原版页面验收](gacha-history-2026-10-12.md)。

分组 ID 和 `pos` 是 TerraLocal 的兼容实现选择：分组依据冻结 GameData 的 `gachaRuleType`，新手归标准、限定/联动归限定、中坚类型归中坚；缺少当前定义的旧记录归历史分组并显示保留标识。没有取得官服认证后的分类 ID 列表，不声称本地 ID 与官服内部编号相同。该页面显示记录，不代表上述所有卡池都已经能够抽取。

初期临时页面的专项 **29 项通过，9.12 秒** 保留为历史证据。最新新增 47 项必要检查，完整 **659 项通过，107.33 秒**，Ruff 无诊断。覆盖认证阶段、账号/游标隔离、同秒分页、并发新行、只读、抽取重试、保存/备份/重启、90 天窗口及时间倒退、坏记录、资源损坏/越界/版本与指纹。新 EXE 实际 TLS 与客户端进程恢复通过，九表及 119 份输入保持；A12 按已验证范围修复。

完整游戏逆向、动态 Lua 分支、所有寻访规则、商店、活动及高级模式、完整断网和两小时游玩仍待完成。管理浏览器先前的保存阻止项没有经本轮操作改变，未借 REA 或其他工具取得被阻止的管理页面。

证据目录：[REA 记录](../.cache/rea-2026-10-12/)、[局部 SDK/native 链](../.cache/rea-2026-10-12/sdk-bridge/native-findings.json)、[实际 U8 阶段](../.cache/rea-2026-10-12/native-auth-stage.json)、[记录专项检查](../.cache/gacha-history-2026-10-12/targeted-tests.txt)。
