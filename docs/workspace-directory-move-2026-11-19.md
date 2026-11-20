# 22 个外部目录迁入项目（2026-11-19）

用户要求把列出的 22 个目录转入 `D:\CODE\VibeCoding\test\TerraLocal` 及其子目录，并要求后续所有新增开发文件均留在本项目内。

22 个目录已全部迁入 **`.cache/moved/<原目录名>/`**，原 D 盘根目录路径均已不存在。采用统一归档位置并保留原名，便于关联原来的构建、失败现场、验收输出和恢复回执。这些目录需要长期保留，不作为可清理缓存，也不收入 Git。

## 目录设计

以下名称均对应 `D:\CODE\VibeCoding\test\TerraLocal\.cache\moved\` 下的同名子目录；完整旧路径和新路径见本地 `path-map.json`。

| 类别 | 保留的目录名 |
| --- | --- |
| Windows 程序验收 | `zy-exe-backup-721a26e` |
| Windows 构建 | `zy-build-721a26e` |
| 编码修复夹具 | `zy-cli-pipe-fixed-a8920ed` |
| 编码失败夹具 | `zy-cli-pipe-before-a8920ed` |
| Windows 失败候选验收 | `zy-exe-backup-a8920ed` |
| Windows 失败候选构建 | `zy-build-a8920ed` |
| MIT 构建安全夹具 | `zy-mit-build-dc36b1` |
| 源码恢复副本 | `zy-source-9ea5f81` |
| 公开仓库下载核对 | `zy-public-7678761f` |
| 迁移定向夹具 | `zy-migration-subset-b8e40d` |
| 迁移历史夹具 | `zy-migration-fixture-a21dd1` |
| 恢复并发现场 | `zy-restore-race-6cd83b` |
| 恢复异常夹具 | `zy-restore-fixture-1eacd9` |
| 恢复修复验证 | `zy-restore-fixed-38b51e` |
| WAL 缺陷复现 | `zy-wal-proof-mkw36w3y` |
| 恢复基线现场 | `zy-restore-base-8c379d` |
| 历次公开下载 | `zy-public-119e9bd2` |
| 原始开发历史恢复 | `zy-history-1ai9uk36` |
| 历次公开下载 | `zy-public-w4754hof` |
| 发布后定向检查现场 | `zyqa-final-d1r91go2` |
| 发布后剩余检查现场 | `zyqa-rest-cfkaic0w` |
| 首次全量检查现场 | `zyqa-a1uj0emj` |

## 实际核对结果

- 移动前后完整遍历：**80,926 个普通文件、2,910,429,928 字节（约 2.91 GB）和 6 个目录连接点**。每个普通文件的相对路径、大小和 SHA-256 均一致；空目录及当时的原始链接目标也逐项相等。
- 先核对源目录、绝对目标边界和目标未占用，再使用原生 PowerShell 移动。迁移前没有运行中的 TerraLocal 服务；没有覆盖旧目录或发行物。
- 完成上述原样核对后，修复 6 个夹具内部的绝对路径 Junction，使其指向迁入后的同一批夹具目录。六个原始 Junction 对象另行保留在证据目录，原目标文字可追溯。
- 5 份 Git 恢复副本的 `fsck --strict` 和干净工作区检查通过。仅一份源码副本的本地 `origin` 指向旧 D 盘根目录历史包，已改为迁入后的同一包；旧 Git 配置另存，提交和对象未改。
- 两个当前检查点索引、三份当前产品记录和五份当前操作脚本已修正。原始记录先完整保留；历史归档中的 JSON、日志、编译时 TOC 和数据库不作批量文本替换，以迁移映射解析旧路径。
- 从新路径直接执行候选 EXE 的只读 `doctor`，退出 **0**；正确读取迁入的合成存档，数据库正常、TLS 就绪、端口可用、`startup_ready=true`。该合成数据的 `client_verified=false`、`ready_for_play=false`，本次未进行原生游戏验收。

文件哈希相同的结论对应“原样移动完成、引用修复之前”。之后有意改变的内容是六个 Junction 的目标及一份本地 Git 配置，均保存旧值。没有以修改历史文件来制造校验一致。

## 本地证据及后续使用

证据根为 `.cache/workspace-move-20261119/`，不提交其中的存档、运行输出或归档内容。

| 文件 | 用途 |
| --- | --- |
| `.cache/moved/path-map.json` | 22 个旧路径到新路径的权威映射 |
| `before-summary.json`、`after-summary.json` 及对应逐目录文件 | 原样移动前后的完整路径、大小及 SHA-256 |
| `move-progress.json` | 实际 22 项移动记录 |
| `junction-fixups.json`、`original-links/` | 六个目录连接点的旧值、新值及原始对象 |
| `reference-fixups.json`、`reference-backups/` | 当前索引、脚本及 Git 本地配置的修正与原件 |
| `current-public-restore-verification.json` | 旧公开恢复证据加迁移后的路径及 Git 核对结果 |
| `doctor-after-move.json` | 新位置实际 EXE 的诊断输出 |
| `final-verification.json` | 最终路径、索引、链接、历史核对和诊断摘要 |

后续需要定位旧 `D:\zy-*` 回执时，先查 `path-map.json`，不要重新创建旧根目录。运行 Python 前加载 `tools/env.ps1`；新增构建、下载、测试、临时文件和恢复目录都放在本项目内。

当前远程核对仍对应公开 `7678761f` 和源码 `9ea5f81`；本次迁移没有产生新的远程发布或源码恢复。新 Windows 候选的功能验收来自迁移前独立记录，本次只补验移动后的路径和诊断。完整服务端、原生玩法及最终发行验收仍未完成。

## 2026-11-20：按用户目录清单再次核对

用户再次要求转移同一批22个目录。实际读取文件系统确认：22个原D盘根路径全部不存在，22个目标均为项目内的实际目录；六个已修复Junction的当前目标与迁移记录一致且存在，原链接对象仍保留。源码恢复副本的本地Git历史包引用指向迁入后的现存文件，归档目录仍被Git忽略。

本次只补记当前路径及引用核对，没有重复移动、覆盖或改写归档内容。80,926文件/2,910,429,928字节的完整SHA-256结论沿用此前移动前后证据，本次未重跑。当前回读保存在 `.cache/workspace-move-readback-20261119T2256464147400Z/verification.json`；没有启动模拟器或操作现用游戏存档。

2026-11-20交接时再次直接核对同一清单：22个原路径均不存在、22个目标均为项目内实际目录，六个Junction目标及原链接备份有效，本地Git历史包引用仍存在，归档仍被Git忽略。新回执为 `.cache/workspace-move-readback-20261120T0504112637243Z/verification.json`。本轮仅新增回执及更新记录，未修改归档内容，未重复完整哈希、程序或游戏验收。
