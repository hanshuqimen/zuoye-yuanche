# `doctor` 启动诊断验收

在已回读源码 `b25b8e7` 上复现了三个问题。对空目录执行诊断会初始化 SQLite 和七个数据子目录。准备好合成数据后，游戏端口已被占用时仍返回 0。损坏的 SQLite 文件会导致异常堆栈。独立 D 盘复现结果在 `.cache/doctor-preflight-20261118/reproduction-v1/verification.json`。

`terralocal --data-dir <目录> doctor` 现在只读所选目录。它复用服务启动时的配置、静态数据和保存绑定校验。诊断在临时副本上检查 SQLite 完整性、实体引用、版本和当前版本所需字段。检查范围包含已提交但尚未写回主文件的 WAL。复制前、复制件和复制后逐文件核对指纹，发现变化时报告 `changing`，应在停止写入后重试。复制适用于本次诊断，正式存档备份仍使用 SQLite 的备份接口。只读打开 WAL 数据库也可能创建附属文件，因此 SQLite 的恢复与校验都在副本中执行。[SQLite WAL 文档](https://www.sqlite.org/wal.html#read_only_databases)

| 退出码 | 启动预检结论 |
| --- | --- |
| `0` | `startup_ready` 为 `true`。端口可绑定，配置和静态数据通过，存档健康或可在首次启动时初始化。 |
| `1` | `issues` 给出待处理项，例如端口占用、缺静态数据、损坏存档、存档变化或待迁移。 |
| `2` | `issues` 给出配置无效或读取校验失败的原因。 |

`database` 为 `not_initialized` 代表尚无存档。`upgrade_required` 代表检测到受支持旧版本，实际迁移由正常启动执行。诊断检查的是一份快照，端口状态也以探测时为准。JSON 中 `client_verified` 和 `ready_for_play` 继续为 `false`，实际客户端、设备和发行包验收另有对应证据。

2026-11-18 的隔离源码验收通过 62 个不同检查，其中 11 个针对 `doctor`，其余涵盖数据校验、备份、恢复和启动服务生命周期。开发环境现有的 Starlette 测试客户端弃用提示仍保留。真实 CLI 子进程完成七个案例。空目录、首次启动前、现行版本、仅存在 WAL 中的旧版本、占用端口、损坏存档、无效配置的退出码依次为 `1/0/0/1/1/1/2`。各次 JSON 可解析、标准错误为空，原路径和文件指纹均一致，临时诊断目录清理成功。使用的都是新 D 盘副本和合成数据。正式发行、原生游玩和设备验收仍待完成。

复验脚本为 `.cache/doctor-preflight-20261118/verify_cli.py`。同目录下 `candidate-v1/checks.xml`、`candidate-v1/checks-doctor-final.xml` 和 `cli-v1/verification.json` 保存检查结果。在已核对源码的独立目录加载 `tools/env.ps1` 后，可运行 `python -m pytest -q tests/test_doctor.py`，再用该脚本指定新的 D 盘证据目录。

源码 `9e33b04` 已保存到私有仓库的 `a95c9db`。实际下载的 3,221,702 字节与清单 SHA-256 `5ac2206bc223885b8adcb8064de741134501a971b0cecaba1320fc59f45547cb` 相符。在新的 D 盘目录恢复出 648 个文件和 324 次提交，Git 完整性检查通过。完整回读记录见 [检查点记录](project-ledger/CHECKPOINTS.md)。

## 2026-11-19 HTTPS 证书预检与续签

在 D 盘测试目录将服务证书与另一个私钥配在一起。原 `doctor` 退出 0 并显示就绪，实际 HTTPS 监听因证书与私钥不匹配而启动失败。

预检与启动现在共用 TLS 文件检查。预检只读文件。启动需要修复服务证书时，用现有 CA 签发新的服务证书并替换服务端证书和密钥。新证书的有效期受 CA 有效期限制。CA 文件不齐、签名或私钥校验失败以及超出有效期都会给出诊断；窗口显示相同的 CA 问题。

| `tls` | 状态 |
| --- | --- |
| `disabled` | 当前配置关闭 HTTPS |
| `will_create` | 首次启动会创建本地 CA 和服务证书 |
| `will_renew` | 启动会用现有 CA 续签或修复服务证书 |
| `ready` | 现有证书满足启动要求 |
| `blocked` | 证书材料需处理，`issues` 列出原因 |

- 修复后，两次独立的监听启动均以启用主机名校验的 HTTPS 客户端收到健康检查 200。首次修复服务证书和私钥，重启复用该服务证书。两次 CA 文件指纹一致。
- 缺少 CA 私钥时，`doctor` 显示 `blocked`，实际启动报告同一问题。该案例的已有证书文件指纹保持，两端口和存档锁可重用。
- 30 项证书、诊断和启动生命周期检查通过。用例覆盖错配、损坏、缺失、错误签发者和到期边界。

验收使用源码和 D 盘合成存档。证据在 `.cache/tls-preflight-20261119/before.json`、`after.json` 与 `tests.xml`。

源码 `b176b80` 已完成私有仓库回读、SHA-256 校验，以及新 D 盘目录对 662 个文件和 347 次提交的核对。[源码回滚点](https://github.com/hanshuqimen/TerraLocal/commit/1a60c7d64a3ae3877de390ac94d40f0e24e4efd0)
