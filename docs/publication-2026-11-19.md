# 「昨夜圆车」公开发布与恢复核对

2026-11-19，用户确认 MIT 并在 GitHub 将仓库设为 Public。连接器读回仓库元数据，随后用不含登录凭据的 Git 克隆验证公众可访问。[公开仓库](https://github.com/hanshuqimen/zuoye-yuanche)

## 已验证的源码版本

发布提交为 `f89163cfbaea793010f46788dde67319819cd1b1`，Git 树为 `1fe000fbd797fa066bfdfe96f14d9627592d3951`。从匿名克隆逐项核对 674 个发布文件的 SHA-256，全部与准备文件吻合，严格 `git fsck` 和工作区检查通过。本文是该版本完成回读后的记录，后续记录提交不计入这 674 个文件。[固定源码版本](https://github.com/hanshuqimen/zuoye-yuanche/tree/f89163cfbaea793010f46788dde67319819cd1b1)

当前 main 包含独立后端、测试、依赖锁、MIT、234 份历史报告及账本。`SOURCE-MANIFEST.json` 对照全部 665 个原始跟踪文件的公开路径及对象，历史辅助源码保存在 `history/source-reference/`。原始文件的完整开发分支保存在 Git 历史包中。客户端、官方资源及 GameData、数据库及存档、凭据、绑定收据、私钥、运行日志、缓存和第三方工具二进制未发布。

公开 main 的启动器不自动连接模拟器，默认只在本机监听。原始设备辅助模块和当时配置完整保存在历史源码及 Git 包中。第三方衍生源码保留相应 BSD 声明；自有源码采用 MIT。既有本地程序、游戏资源、原存档和旧发行目录保留。

## 原始开发历史

公开文件 `history/source-history-d40aee9.bundle` 为 3,683,110 字节，SHA-256 为 `b4888ed42cd987b5e7531c8d49a5123b1ecb835f04526bf1d483c35d34784f83`，Git blob 为 `3145643b265094a4988db889b0b4a6e2c1cfe584`。[完整历史包](https://github.com/hanshuqimen/zuoye-yuanche/blob/f89163cfbaea793010f46788dde67319819cd1b1/history/source-history-d40aee9.bundle)

用公开下载的包在另一新 D 盘目录恢复 `codex/development`。恢复头为 `d40aee9aa816db5c447bf908da4335d5a7731648`，353 个原始提交和 665 个原始文件对象全部吻合，严格 Git 检查和干净工作区检查通过。历史包中的路径和当时配置与当前 main 的独立启动说明分别保留。

```powershell
git clone --branch codex/development history/source-history-d40aee9.bundle restored-history
```

## 实际检查与未完成项

全部 3,203 项自动检查已执行且每个用例只计一次：3,187 通过、15 失败、1 跳过。11 项失败涉及旧版本迁移的表数量断言，4 项应拒绝的无效备份被接受。15 个用例的名称及逐项结果已公开，尚未修复。跳过项缺少可选的冻结官方数据。[检查报告](https://github.com/hanshuqimen/zuoye-yuanche/blob/f89163cfbaea793010f46788dde67319819cd1b1/VALIDATION.md) · [逐项结果](https://github.com/hanshuqimen/zuoye-yuanche/blob/f89163cfbaea793010f46788dde67319819cd1b1/validation/results.json)

本机真实 HTTPS 检查覆盖健康、登录、写入、同步、备份、停止和新文件恢复；四次接口调用返回 200，恢复文件的 SHA-256 与回执一致。第一次发布检查缺少合成测试辅助，补齐后遇到 Windows 深路径限制；改用 D 盘短路径继续完成原集合。这些失败保留在本地证据，未当作原生通过。

本阶段没有新原生游玩，也没有验收新公开版 Windows 包。完整玩法、原生画面、整机断网、长时游玩和 HarmonyOS 验收仍未完成，公开发布不代表成熟私服已交付。下一修复先调查四项无效备份接受，再核对旧迁移断言的真实结构和数据保全。

## 旧仓库与后续目标

旧私有仓库的最后核对 main 为 `4b334d24a105de73bd303cc1497b05665772e826`，树为 `ef8209464c9bcffc14916fef599b5f694f8488d6`。290 个文件共 294,345,318 字节已完整保存在 D 盘，含 144 个完整 Git 包。逐文件 Git 对象及完整树均与远端一致，独立本地快照通过严格 Git 检查。

用户已授权删除旧私有仓库。连接器不支持仓库删除，电脑操作工具因不能可靠识别浏览器网址停止；已请用户在旧仓库 Settings 的 Danger Zone 完成删除。最后回读旧仓库仍存在，因此删除仍为待完成项。未提取浏览器凭据或绕过工具停止。

开发目录的 `origin` 已指向新公开仓库，旧地址以 `terralocal-retired` 保留。既有提交、备份及失败副本保持；没有 reset、clean 或强制推送。下一源码和检查点以公开仓库为目标。
