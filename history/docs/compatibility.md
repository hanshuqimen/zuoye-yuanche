# 客户端兼容性

2026-10-08 自有雷电基线。整体配置仍标记 `client_verified=false`；局部通过流程单独记录。

| 字段 | 读取值 |
|---|---|
| emulator | LDPlayer9 9.5.6.0，D:\\leidian\\LDPlayer9 |
| Android | 9 |
| package | com.hypergryph.arknights |
| versionName / versionCode | 2.7.71 / 190 |
| app ABI | arm64-v8a；宿主 Android 提供 x86_64 与 ARM 转译 |
| resourceVersion | 26-09-22-07-47-20_6c71fa |
| resource / network / config | V077 / V070 / 5 |
| GameData | Stream://torappu-data/v077/rel77.0；Change 123576 on 2026/09/17；77.6.0 |
| helper / login / battle | 静态适配 v2、本地登录及主页已局部验证；战斗未验收 |

原实例 index 0 保留；仅测试实例 index 1 使用本地适配 APK、自有凭据、可撤销 hosts/系统 CA 覆盖、
ADB reverse 和按应用 UID 限制的外网规则。安装及资源回执保存在本地，不复制官方认证资料。

| 指纹 | SHA-256 |
|---|---|
| 原始 APK | `0b79b85383e21a6343283bc6bfd7a9d24eb4134abf901115f757da6a5d50f6db` |
| 静态适配 v2 APK | `f75a9643d2d3fb487e5da082492cb2336bce399cabdc0725a895efd186df2e01` |
| 冻结客户端 metadata | `bf14421bbafe9c71d944ba4f97b31ecd666232640eac0829db3d84ac716ac8b8` |

| 配置 | GameData SHA-256 | 表数 | 处理 |
|---|---|---|---|
| cn-android-2.7.71 | `f310854b059ce71ed9be05eceabe143d9f8cadbc6545fb033ac136ffc68285d0` | 15 | 原始冻结配置保留 |
| cn-android-2.7.71-voice | `857a63c649e619e4f07308ff77e714c573fb5170b695570562790e4b131a4fc3` | 16 | 增加语音表，原 15 张表不变 |
| cn-android-2.7.71-home | `23be07863779d49ec682b6e06d951738b3a2a87d297d6f4b85aafe824eee042e` | 17 | 保留；增加剧情表，原 16 张表不变 |
| cn-android-2.7.71-display | `f44199a7d34a82bdbb232674db3a3cdf9d7958230217fce3960ccafd351b7406` | 18 | 当前选择；增加默认背景/主题表，原 17 张表不变 |

新增表来自 [不可变 GameData revision](https://github.com/Kengxxiao/ArknightsGameData/tree/a550f5e048bb94e7cdefc6eb97a4091f0c4c7add/zh_CN/gamedata/excel)，
准备时验证 data_version 与基线相同并保存原文件 SHA-256、导入指纹和来源回执；运行时只读本地缓存。

已实际通过静态 SDK 更新、本地 U8 认证、游戏登录、syncData、账号说明 WebView/接受保存、
未确认订单读取、批量中文语音切换和主页渲染。刷新响应仍有客户端更新错误，剧情完成尚待实际提交。
首个战斗、干员详情、主要系统、完整断网、两小时游玩和 HarmonyOS 均未验收。

资源验证包括原目录 11,755 个文件名称/大小，以及下载 ZIP 成员的 manifest MD5/大小。
匿名 metadata 包的四位校验格式尚未支持。日语四个可选包已缓存验证，客户端安装仍待验证。
公开表尚未与自有 FBS 全表逐字段核对，不能据此宣称全部字段和系统与官服一致。

官服 IL2CPP 声明、静态注册表及部分调用路径已建立可查询索引，详见 [分析记录](client-analysis.md)。
函数地址与类型信息是兼容依据，不能作为功能已实现或客户端已通过的证据。
