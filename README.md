# 昨夜圆车

本地服务源码、存档工具与开发进度。当前源码基线为 `d40aee9`，项目的入口命令保留为 `terralocal`。

## 运行

使用 Python 3.12 和项目的 `uv.lock`。在仓库目录运行以下命令。

```powershell
uv sync --locked
uv run terralocal --data-dir .\data serve
```

服务和管理接口默认在本机监听，端口分别为 8443 和 8080。首次运行后可用 `uv run terralocal --data-dir .\data doctor` 查看配置、存档、证书和静态数据。需要数据的接口使用自行准备的匹配表。自动检查使用项目自有的合成数据。使用 `uv run pytest -q` 运行仓库中的检查。

代码支持事务写入、增量同步、请求重试、备份、独立恢复和启动诊断。此公开版本按独立后端运行。原版客户端接入、各玩法完成度和发行物的实际边界见[开发进度](PROGRESS.md)。

历次阶段报告与项目账本收录于[开发记录](history/README.md)。完整源目录的公开路径、哈希和本次发布调整见 [SOURCE-MANIFEST.json](SOURCE-MANIFEST.json)。

自有源码采用 [MIT 许可证](LICENSE)。
