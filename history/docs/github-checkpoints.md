# GitHub 回滚检查点

用户于 2026-10-12 授权使用其 GitHub 账号新建仓库并定期上传开发修改。
目标为私有仓库 `hanshuqimen/TerraLocal`，本地开发分支使用 `codex/development`。

只提交自有服务器、工具、测试、依赖锁和说明。客户端 APK、官方资源、GameData、
数据库、存档、绑定收据、凭据、证书私钥、运行日志和逆向工具缓存保留在本地忽略目录。
不使用强制推送、清理工作区或覆盖旧发行目录进行回滚。

网页创建私有仓库和首个备份提交已成功，远程提交为
`d08eadec49fc16f1647af64d02535896d6fb3adc`。当前连接器仍不能读取该私有仓库（404），
本机没有可复用的 Git 凭据，因此主分支暂以 Git bundle 保存完整源码历史；
尚未直接推送可在网页浏览的源码分支，也没有扩大连接权限或提取浏览器凭据。

本地源码提交 `b1fe856138a51dc451a9c939b8171afb87515cf0` 包含 211 个文件。
上传的 `TerraLocal-baseline-20261012.bundle` 经 GitHub 页面下载回读，543,834 字节，
SHA-256 为 `e81bd526e37f2aa675881de9676258ab97f6b28395639ed4c54e97cc8f60aa81`。
已验证完整 Git 历史，并在新的 D 盘目录恢复，提交及 211 文件一致。
恢复只用于核查，没有替换当前工作区或接管现有存档。

2026-10-13 看板与服装检查点已保存，远程提交
`8ae21cae7a30697ab93c693df22d12c99da73edb`，源码提交
`a531d37ec7fe57b692c34d6f672d22eaabb22197`，229 个允许文件。
`TerraLocal-home-20261013-a531d37.bundle` 为 611,213 字节，SHA-256
`8ccd477f6e809a0ac2a148654cf38ce128077200e37eb9a9316be4f1a78a475f`。
全历史 274 个 blob 的路径及凭据模式检查通过；网页回读哈希匹配，
在新的 D 盘目录以 core.autocrlf=false 恢复，229 个文件与提交的 Git blob 字节一致，工作区干净。
该检查点有 787 项检查、服装 EXE 原生购买/穿戴/重启；看板原生保存仍待验收。
之后发现的看板整数布尔兼容修改不在此 bundle 中，应另存后续检查点，不能将其视为已上传。
旧 bundle、旧发行目录和原存档保留；新 0011 存档不允许交给旧程序降级打开。

此前信用检查点实际远程提交为 `105a4056192c00e2789e12167741e22884307a51`，
源码 `bd5c564aed04db3443e4137d0a11ee8fdad3a093`，215 文件。
`TerraLocal-credit-20261012-bd5c564.bundle` 为 565,807 字节，SHA-256
`2f72fa34b2188e1e17f063f24d34b9fec04bc794b4eb2d3043d6e3dd7ebec2e4`。
网页回读和新 D 盘目录恢复通过；当时 170 份源码与工作区比较为 168 份字节一致、
两份仅为旧 Git 换行规范化差异，没有把它记录为全部工作区文件字节一致。

第二份原版寻访记录页面检查点已上传，远程提交
`ff270dd05483c874f080648e83b85bb61d2ea9b0`，源码提交
`88c875a139d8feb35a724a882b25a0a7097665a0`，包含 214 文件和完整历史。
`TerraLocal-a12-20261012-88c875a.bundle` 为 559,819 字节，SHA-256
`d43a3d40d45ce8f18c30e077f3cd39324d00d41f42cfbad39b790077d9c6edc5`。
再次通过网页下载回读、Git bundle 校验和新 D 盘目录恢复，提交与文件数一致。
该检查点包含 A12 的 659 项检查及原版新 EXE/客户端重启证据；A13 信用映射在该提交中仍待修复。

已创建本聊天的每小时检查点任务 `terralocal-github`：有新修改时核查并保存，
没有修改则不生成重复提交。计划存在不等于每次运行都成功，后续仍须记录实际远程提交和回读。

2026-10-14 补领修复源码检查点已经验证。源码提交
`8437f8d969c1be09de029b9be7711e4d1dbfbb2f`，远程私有网页提交
`bbf1ffba3b32b0dbcde84b95ded1ed25f071c8d7`；bundle文件为
`TerraLocal-cash-recovery-20261014-8437f8d.bundle`，668,376字节，SHA-256
`64748627b73dcebe78b22cafb75262a4f79be8b21b269fb58a4d2957dc486d22`。
扫描完整12个提交、241个历史路径及342个文本blob；禁止路径与凭据模式命中均为零。
网页下载回读、bundle校验和新D盘目录恢复通过，240个文件与提交Git blob逐字节相同，fsck及干净工作区检查通过。
仍通过授权的私有网页保存完整历史；没有直接推送源码分支，没有扩大权限或读取浏览器凭据。
该检查点保存876项检查后的源码修复，提交时新EXE原生复验仍待完成；后续新增的实际验收/组合包调查文档需要另存检查点，不能倒称已包含在此bundle中。

初始检查点属于开发状态：A09 性能修复已验收；A12 历史查询后端有专项检查，
临时自制页面只用于验证协议。原版页面资源接入、原生画面、完整回归及新 EXE 仍待完成。
完整逆向、所有卡池和主要高级玩法仍未完成，不能将检查点当作成熟发行版本。

## 2026-11-19 公开发布核对

用户要求在 GitHub 完整公开项目进度。现有 `hanshuqimen/TerraLocal` 仍为私有，main 提交 `cb4927a` 有 288 个条目，其中 143 个为完整 `.bundle` 文件。远端列出一个分支、零个 Release 和零次 Actions 运行。已从最新包的独立恢复确认，历史含针对官方客户端的 APK 改包源文件和私有项目记录。[私有检查点](https://github.com/hanshuqimen/TerraLocal/commit/cb4927a8d1d7c3c7d8c5f15b0c957fcd16f1f64c)

本地核对 664 个跟踪文件。61 个文件含本机路径或测试实例引用。检查未发现被排除的文件类型或常见凭据格式命中。仓库根目录暂无项目级许可证，已有的 BSD 3-Clause 说明随第三方工具来源保留。证据在 `.cache/publication-review-20261119/scope-tliqq2pb/local-scope.json`。

GitHub 将现有内容随仓库公开，访问者可以 fork，已创建的副本可在再次设为私有后保留。已请用户确认另建公开源码仓库的发布范围及项目许可证，目前等待确认。公开记录应覆盖历次已验证结果、未完成项及验证范围。[GitHub 可见性说明](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/setting-repository-visibility) · [GitHub 许可证说明](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)

以本地 `4529780` 为基线，在 D 盘生成发布审阅文件。`PROGRESS.md` 汇总当前验证与剩余范围，列全 351 个提交的日期、短标识和摘要。`source-files.csv` 对照同一源码树登记全部 664 个文件的相对路径、字节数和 Git 对象，标出 98 个需要逐项复核的文件。其中包含本机测试信息、内部账本或客户端工具。目录为 `.cache/publication-review-20261119/release-review-e1qfipqd`，文件指纹见同目录 `review-proof.json`。审阅材料留在本地，公开仓库和许可证等待用户确认。

已逐项核对全部 98 个标记文件的基线 Git 对象、用途和发布建议。启动器确实直接导入 `client_binding.py`，公开源码如包含启动器，需要保留账号及设备校验，并处理配置、绑定与测试夹具中的本机值。第三方 BSD 声明已核到对应衍生源文件。逐项结果在 `.cache/publication-review-20261119/file-review-tcivs5co/publication-actions.csv`，SHA-256 见同目录 `file-review-proof.json`。公开范围与项目许可待确认。

进一步追踪查到 `android.py` 和其测试也使用同一台设备的标识，补充原审阅的遗漏。在 D 盘 `portable-check-odacu2zn` 中调整了五个源码或测试文件，配置默认空设备路径，测试使用合成身份。72 项相关检查和本机实际启动、在线备份、停止通过。预检拒绝无设备配置的连接，保留严格设备校验。该副本仅用于审阅，既有源码和发布物沿用原配置，公开发布仍待确认。
