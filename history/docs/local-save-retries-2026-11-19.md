# 本地存档重试与版本核对

旧版把本地写入的 `Idempotency-Key` 和 `seqnum` 都按登录会话记录。使用隔离的合成存档，先后提交两个名称，获得版本 1 和 2。重新登录后携带第一次的键和请求体重试，旧版把名称写回第一次的值，生成版本 3 和第三条执行记录。

`/local/v1/` 的显式 `Idempotency-Key` 现在按已认证账号、操作和键查询。第一次写入与回执在同一 SQLite 事务提交。重复请求返回第一次的结果、增量和版本。同一键提交不同请求体会返回 `409 IDEMPOTENCY_CONFLICT`。调用方应为每次新的写入生成独立的键，并在跨登录重试时保留该键和原请求体。使用 `seqnum` 的接口仍按登录会话识别重试。

回执中的版本代表原操作的提交版本。调用方已接收更新版本时，应跳过较早回执附带的增量。对当前状态有疑问时，以 `/local/v1/sync` 返回的全量数据为准。

数据库无需迁移。旧回执只含会话范围的摘要。原会话中匹配的旧回执会保留并登记为可跨会话重试，同会话内请求体冲突仍会拒绝。升级前未登记就结束会话的旧请求缺少可跨会话识别的记录。`seqnum` 模式下旧号仍有效，切换到显式键时应使用独立的键值，以免匹配当前会话中的旧记录。

## 已执行的验证

- 68 项相关检查通过。新增用例覆盖两个有效会话并发只提交一次、重新登录和重启后重试、旧回执登记、冲突和超时会话、账号隔离。格式检查通过。
- 使用 D 盘隔离的合成存档执行两次本机 HTTPS 启动与停止，校验证书。八次请求返回七个 `200` 和一个预期的 `409`。重启后旧请求返回完整的版本 1 回执，实际全量同步仍为版本 2 和最新名称，数据库只有两条回执。
- 复现和通过证据分别位于 `.cache/local-retry-20261119/before-741urva9/result.json` 和 `.cache/local-retry-20261119/after-https-gi1wx4ci/result.json`。使用 `. .\tools\env.ps1` 后运行 `.\.venv\Scripts\python.exe -m pytest -q tests/test_local_retries.py tests/test_session_battle_invariants.py tests/test_transactions.py tests/test_squad_protocol.py tests/test_sync_projection.py tests/test_credit_sync.py` 可重跑相关用例。

本次验收覆盖源码与本地服务。已发布 Windows 程序需另行打包和核验，真实客户端的数据更新故障未经本次复验。

源码 `069c678` 已从私有仓库实际下载并在 D 盘新目录恢复，逐文件核对 664 个文件及 349 次提交。远端原有 286 个条目均保持。 [私有检查点](https://github.com/hanshuqimen/TerraLocal/blob/cb4927a8d1d7c3c7d8c5f15b0c957fcd16f1f64c/TerraLocal-local-retry-20261119-069c678.bundle)
