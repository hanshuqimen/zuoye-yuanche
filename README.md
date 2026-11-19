# 昨夜圆车

本地服务源码、存档工具与开发进度。当前源码基线为 `d40aee9`，项目的入口命令保留为 `terralocal`。

## 运行

使用 Python 3.12 和项目的 `uv.lock`。在仓库目录运行以下命令。

```powershell
uv sync --locked
uv run terralocal --data-dir .\data serve
```

服务和管理接口默认在本机监听，端口分别为 8443 和 8080。首次运行后可用 `uv run terralocal --data-dir .\data doctor` 查看配置、存档、证书和静态数据。需要数据的接口使用自行准备的匹配表。自动检查使用项目自有的合成数据。使用 `uv run pytest -q` 运行仓库中的检查。首次完整检查为 3,187 项通过、15 项失败、1 项跳过。随后原 15 个失败已定向复验通过，211 项相关检查通过，详见[发布验证](VALIDATION.md)。

代码支持事务写入、增量同步、请求重试、备份、独立恢复和启动诊断。此公开版本按独立后端运行。原版客户端接入、各玩法完成度和发行物的实际边界见[开发进度](PROGRESS.md)。

历次阶段报告与项目账本收录于[开发记录](history/README.md)。完整源目录的公开路径、哈希和本次发布调整见 [SOURCE-MANIFEST.json](SOURCE-MANIFEST.json)。

全部 665 个原始跟踪文件均有公开路径，历史辅助源码见[历史源码参考](history/source-reference/README.md)。

自有源码采用 [MIT 许可证](LICENSE)，带有第三方声明的历史文件沿用对应声明。

## 完整开发历史

[Git 历史包](history/source-history-d40aee9.bundle)包含 353 个原始开发提交和当时的全部 665 个跟踪文件。校验摘要见[历史包清单](history/source-history-d40aee9.json)。可在新目录恢复原始开发分支。

```powershell
git clone --branch codex/development history/source-history-d40aee9.bundle restored-history
```

历史包保留原始开发目录和当时配置。当前可运行入口以此仓库 main 分支说明为准。

公开访问、匿名下载、历史恢复及旧仓库迁移的实际结果见[发布核对](docs/publication-2026-11-19.md)。

后续备份与旧迁移修复见[修复记录](docs/backup-domain-validation-2026-11-19.md)。[历史增量包](history/source-updates-9ea5f81.bundle)在上述完整包基础上恢复至 9ea5f815abd2e6ef3b43e7a3476013914000ba7f，共 356 个提交、668 个跟踪文件。先按上文恢复，再执行：

```powershell
git -C restored-history fetch ../history/source-updates-9ea5f81.bundle codex/development
git -C restored-history merge --ff-only FETCH_HEAD
```
