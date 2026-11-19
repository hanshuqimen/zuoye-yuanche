# 官服客户端分析记录

2026-10-08，使用本地保留的官服 CN Android 2.7.71 / 190 APK。
原始 APK、资源和分析产物保留在 D 盘；原模拟器 index 0 未修改。
当前成果是完整的 IL2CPP 声明索引和部分调用路径，尚未还原全部函数体、动态调用和业务规则。

2026-10-12 补充：已实际使用 REA 6.4 的 Android/JavaScript 操作恢复寻访 WebView getter，并以 13 个离线 native 局部范围和原生实际 U8 认证交叉验证。`static-address-body-protected` 为旧保守分类，不能据此判定每段 native 都不可读。最新证据与完整覆盖缺口见 [REA 调查](rea-investigation-2026-10-12.md)。

## 输入与可复核产物

| 输入 | SHA-256 |
|---|---|
| 官服 APK | `0b79b85383e21a6343283bc6bfd7a9d24eb4134abf901115f757da6a5d50f6db` |
| ARM64 libil2cpp.so | `3ece1e7b34165233fe8c3c919cf55dfcb4406b6bbc2725def2b1242b4c0a6259` |
| global-metadata.dat | `bf14421bbafe9c71d944ba4f97b31ecd666232640eac0829db3d84ac716ac8b8` |

重新核对原始 APK 和上述两个 ZIP 成员的指纹后构建索引。
静态适配 APK 仅改动 SDK 层；读取加载后注册表时另核对测试实例安装的 ELF 指纹。
分析产物在 `.cache/client-metadata`，不进入发行目录。

| 产物 | 内容 |
|---|---|
| official-index.sqlite3 / .json | 类型、父类、嵌套类型名称、字段、函数参数和返回类型、地址、泛型注册表、构建回执 |
| protocol-contracts.json | 请求/响应/结果类型候选及字段；不能直接等同于网络 JSON schema |
| loaded-tables/receipt.json | 119 个有指纹的静态表切片，共 6,975,488 字节 |
| *-calls.json | 选定已加载代码中的 ARM64 直接调用与尚未解析的间接调用 |

2026-10-08 09:46:48 UTC 索引 SHA-256：
`30c555d4479d4a0f708b9fc61aa4ecfeb945a169e4a82586e31d243afdaa4804`。
SQLite integrity_check 为 `ok`，声明字段类型均已解析。

## 覆盖范围

| 项目 | 数量 | 含义 |
|---|---:|---|
| 程序集 / 模块 | 88 | IL2CPP metadata image 与 code-generation module 对照 |
| 类型 | 49,382 | 包含游戏、Unity 和库类型 |
| 字段 | 361,839 | 声明完整覆盖，不代表网络必填字段 |
| 函数声明 | 299,831 | 声明完整覆盖，包含参数、返回类型和 token |
| 非零静态函数地址 | 282,278 | 函数体仍受保护，地址不能证明行为已还原 |
| 泛型实例参数集合 | 31,297 | 已解析参数类型 |
| method-spec 记录 | 290,772 | 全表索引及范围校验 |
| 泛型函数映射 | 210,466 | 关联 10,233 个此前地址为零的函数声明；共享函数体可对应多个实例 |
| 请求/响应类型候选 | 1,585 | 按游戏程序集及类型名筛选，含部分非网络类型 |
| 候选类型声明字段 | 2,631 | 父类字段在各自声明类型中列出 |
| 路由字符串候选 | 111 | 需与调用位置和实际请求对应，不是已支持接口列表 |

`enum2int.dll` 的两个指针位于 ELF 零填充区，保持未解析。
2,048 条 managed literal 定义有额外保护，未伪造解码结果。
泛型字段偏移可能是占位值，静态字段偏移是静态存储内的相对值；不能当作所有运行时对象的实际偏移。

## 解析与调用路径

metadata 中的定义可能跨越 4 KiB 保护页。仅按末尾 token 对整行 XOR 会损坏另一页中原本正确的字段。
当前工具使用多种独立 token 判定每页，并拒绝互相矛盾的证据；标识符页另外校验文本和 NUL 分隔符。
新增测试覆盖跨页行、矛盾标记及全大写标识符页；函数索引测试另覆盖泛型地址分类、外部分支和切片指纹拒绝。
本轮 104 项回归通过（10.02 秒），修改文件 Ruff 通过。

从测试实例读取的范围限于已校验 ELF 的文件映射。静态表按最多 64 KiB 切片读取；
静态表工具不读取匿名映射、玩家对象、SDK 文件或认证资料。
日志检查工具另外仅读取已核对类型名称的 DLog / Unity Logger 配置小字段，不读取玩家对象或认证资料。
加载后的 method-spec 表校验全部通过，解决了只读原始 ELF 时遗漏泛型处理函数的问题。

已定位的核心地址包括：

| 函数 | ARM64 RVA |
|---|---|
| PlayerDataRequestHandler.DeserializeResposne<object> | `0x633a5d4` |
| PlayerDataRequestHandler.HandleResponse<object> | `0x633a7a0` |
| PlayerDataRequestHandler._DeserializeResponse<object> | `0x633ad3c` |
| PlayerDataRequestHandler._ProcessPlayerData<object> | `0x633afc4` |
| _DeserializeResponse 的工作闭包 | `0x64c8dc0` |
| PlayerDataDelta.Apply | `0x4028b14` |
| PlayerData.NotifyDataChanged | `0x40278b0` |
| UISyncDataUtil._UpdateCacheAfterSyncStatus | `0x33bf0a4` |

反序列化工作闭包会检查响应的类型，提取初始化数据或增量；非空增量需要已有 rawPlayerData，
否则代码存在抛出 InvalidOperationException 的分支。增量应用后才通知玩家数据变化。
这确认了需要继续检查的路径，尚不能确定当前客户端刷新错误由其中哪一处分支触发。
2026-10-08 10:24 / 10:27 / 10:34 UTC 的三组副本诊断仍显示“数据更新失败”，详见 [刷新诊断](refresh-diagnostic.md)。

直接调用报告记录代码位置、目标地址和声明匹配；另列出范围外 B 和 BR，范围外分支并不证明一定是尾调用。
查询结果区分已注册静态地址、泛型地址和无地址；旧 address_status 字段保留，但两者均不能证明行为已还原。
BLR、虚调用及 XLua 热修复分派单独保留为缺口，
不把线性反汇编称作完整调用图。

CommonSyncServiceItem 的普通结果构造分支会把非空 JObject 转成字符串，再用 Networker 的设置反序列化到模块类型；
空结果直接返回默认值，异常分支记录错误后返回默认值，入口另有 XLua 分派。
RespMsgBundle 的普通分支使用 JsonConvert，定制 bundle 使用自己的 Deserialize；存在异常包装分支。
StageDataUtil.GetMainStageProgress 读取玩家字段并调用 GetStageIgnoreTime，尚不能据此确定应写入最后完成还是下一关。

## 工具使用

```powershell
. .\tools\env.ps1
# 已运行且身份匹配的独立测试客户端：读取固定的静态注册表。
.venv\Scripts\python.exe tools\research\read_client_tables.py --generic
.venv\Scripts\python.exe tools\research\index_client.py build --refresh
.venv\Scripts\python.exe tools\research\index_client.py query PlayerDataRequestHandler
.venv\Scripts\python.exe tools\research\index_client.py contracts
.venv\Scripts\python.exe tools\research\index_client.py calls .cache\client-metadata\live-request-handler.bin --rva 0x633a7a0 --size 0x994
```

结构布局参考 [Il2CppDumper metadata 定义](https://github.com/Perfare/Il2CppDumper/blob/master/Il2CppDumper/Il2Cpp/MetadataClass.cs)
及 [IL2CPP 原生注册结构](https://github.com/Perfare/Il2CppDumper/blob/master/Il2CppDumper/Il2Cpp/Il2CppClass.cs)，
反汇编使用 [Capstone Python API](https://www.capstone-engine.org/lang_python.html)。
这些资料用于理解布局；本项目工具独立实现，并仅接受本次冻结指纹。

接下来继续对应路由与请求/响应别名，分析动态 Lua 热修复和战斗编码，
再逐个建立协议 fixtures、实现领域行为并进行真实客户端验收。
