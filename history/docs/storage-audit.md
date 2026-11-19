# C 盘空间只读审计

测量日期：2026-10-07，约 14:57–15:02（北京时间）。本报告记录**迁移前**状态。仅枚举文件大小、文件时间和目录名称；未读取凭据、聊天正文或个人文档，未删除、移动文件，也未修改系统设置。精确字节数及明细见 `storage-audit.json`。

本次没有发现 TerraLocal 的约 20 GB 下载或解包文件落在 C 盘。当前最大的相关候选是系统自动管理的 **10 GiB 分页文件**，但缺少运行前的分页文件大小，不能证明这 10 GiB 都是本次新增，也不能据此解释全部约 20 GB 减少。游戏 APK、研究工具和测试模拟器的虚拟磁盘均位于 D 盘。

| 项目 | 迁移前字节数 | 大小 | 时间与归因 |
|---|---:|---:|---|
| `C:\pagefile.sys` | 10,737,418,240 | 10.00 GiB | 系统自动管理；最后写入时间 14:52:07；文件创建于 7 月 22 日，无增长基线。 |
| `C:\swapfile.sys` | 16,777,216 | 16 MiB | 最后写入时间今天 07:28，未见本任务证据。 |
| `C:\hiberfil.sys` | 不存在 | — | 已查询确认不存在。 |
| `<user-home>\AppData\Local\uv\cache` | 1,869,504,046 | 1.74 GiB | 60,520 个文件；检查中没有中午后新建或修改的文件。最大文件为 10 月 5 日的 Torch 缓存。属于共享工具历史缓存，不是本次新下载的 20 GB。 |
| `<user-home>\AppData\Roaming\uv\python` | 63,200,572 | 60.27 MiB | Python 3.12.13 创建于 8 月 10 日；没有版本号的目录是 junction，已排除重复计数。 |
| `<user-home>\AppData\Local\Temp` | 3,612,499,454 | 3.36 GiB | 其中中午后新文件共 145,716,385 字节，约 139 MiB。全部 Temp 不可归因于本任务。 |
| Temp 下 `pytest-of-ASUS` | 8,872,564 | 8.46 MiB | 今天 14:24–14:25 的测试临时数据，可归因 TerraLocal 测试。 |
| Temp 下 `gbahbxhi.nns` | 131,469,618 | 125.38 MiB | 今天 14:25 创建；包含 `vs_installer.exe`、`setup.exe`、`Microsoft.VisualStudio.Setup.ToastNotification.exe`，属于 Visual Studio Installer 解包，未见 TerraLocal 相关内容。 |
| Temp 下 `hbqzgq1h` | 2,080,685,961 | 1.94 GiB | 10 月 5 日的 Visual Studio VSIX/Windows SDK 安装包，不是本任务新增。 |
| `<user-home>\.codex` | 2,290,624,617 | 2.13 GiB | 桌面应用共享会话、插件及数据库；中午后新文件当前大小约 161 MiB。修改过的大文件当前大小不是增长量，不能把整份历史数据库算成本次新增。 |
| `<user-home>\.cache\codex-runtimes` | 1,987,190,838 | 1.85 GiB | 检查中没有中午后新建或修改文件；运行库及安装归档在本任务前已存在。 |
| `<user-home>\AppData\Local\skylot\jadx` | 0 | 0 | 今天 14:41 创建的空目录。JADX 程序本体已保存在 D 工作空间。 |
| `<user-home>\.Ld9VirtualBox` | 1,716,415 | 1.64 MiB | 雷电共享日志与设置，非虚拟机资源本体。 |
| `<user-home>\AppData\Roaming\leidian9` | 202,233,611 | 192.86 MiB | 日志约 58 MiB，启动器图片缓存约 133 MiB；中午后新文件共约 3.65 MiB，包括测试实例日志、游戏图标和启动器图片。 |

分页文件查询同时显示：AllocatedBaseSize = 10,240 MiB，CurrentUsage = 853 MiB，PeakUsage = 1,811 MiB。机器物理内存约 15.22 GiB（系统可见值）。这些是查询当时的快照，不能推算本次开发导致的历史分配增量。C 盘当时空闲 43,243,130,880 字节，约 40.27 GiB。

## 已确认放在 D 盘的大文件

- 工作空间 APK：`data/client/base.apk`，1,882,311,496 字节。
- 工作空间 Frida Server：`tools/local/frida-server`，116,322,840 字节。
- 工作空间 JADX JAR：`tools/local/jadx/lib/jadx-1.5.3-all.jar`，127,558,582 字节。
- 独立测试实例：`<emulator-directory>\vms\leidian1\data.vmdk`，4,491,968,512 字节；`sdcard.vmdk`，27,989,311,488 字节。两文件创建于今天 13:51。这里是虚拟磁盘文件逻辑大小，未等同为游戏资源大小或实际 NTFS 占用。

## 项目局部迁移建议

1. 把共享 uv 缓存迁入工作空间 `.cache/uv`，把项目使用的 Python 3.12.13 运行库迁入 `tools/local/python`。搬移前检查没有使用这些路径的活动安装任务；复制或搬移后校验文件数量、大小和解释器启动。保留旧路径到新路径的 junction 可以兼容其他项目已有的解释器引用；不要造成其他项目失效。
2. 项目启动脚本为当前进程设置 `UV_CACHE_DIR`、`UV_PYTHON_INSTALL_DIR`、`TEMP`、`TMP`、`TMPDIR` 到工作空间对应目录；Pytest 使用项目内 `--basetemp`，JADX 使用项目内 `-Djava.io.tmpdir`。这些设置不修改用户或系统的全局环境变量。
3. 项目下载、解包、构建和运行数据继续存放 D 工作空间。发行物使用目录式运行依赖，避免每次启动向 C Temp 解压一整套运行库。
4. 不搬移正在使用的 Codex 会话/数据库和共享插件；不清空无关 Visual Studio 临时目录；不直接删除或修改系统分页文件。减少同时运行的模拟器实例可降低内存压力，但能否收回分页文件空间须依据系统后续状态，不能保证。

迁移 uv 缓存和解释器最多可转移约 **1.80 GiB** 的当前逻辑文件数据。它们大多是历史缓存，不能作为“本次新放入 C 盘的 20 GB”处理。要严格证明约 20 GB 减少的原因，需要更早的 C 盘/分页文件基线，或扩展到非项目软件的独立磁盘审计；本报告不凭空归因。

统计限制：目录大小为逻辑文件大小，未计算 NTFS 每个簇分配和稀疏文件占用；文件新建/修改计数只反映扫描时现有文件，不能捕捉已删除的临时峰值；复制、归档解包可能保留原有时间戳。检查中未出现拒绝访问的目录；明确排除了凭据/secret 目录。

## 实际迁移与项目配置记录

记录时间：2026-10-07 15:14。后续范围收紧为保留共享 C 缓存、让 TerraLocal 后续开发使用 D 路径。以下区分实际迁移和仅复制，未把复制当作 C 盘空间释放。

- 预检发现项目原来的 `.cache/uv` 已有 **333,639,504 字节、5,023 个文件**，创建时间为今天 13:47–14:15，包含 Frida、Ruff 和 frida-tools。**这些本项目安装缓存在迁移前就位于 D 盘。** 为保留它们，已在工作空间内原样改名为 `.cache/uv-project-before-migration-20261007`，未删除。
- C 共享 uv 缓存的 **1,869,504,046 字节、60,520 个文件、8,202 个子目录**已完整复制到 D `.cache/uv`。所有相对路径、文件长度和目录清单一致；最大 15 个文件及两个缓存标识文件的 SHA256 一致。**C 原 uv 缓存仍完整保留，无 junction，没有因此释放 1.74 GiB。**
- Python 3.12.13 的 **63,200,571 字节、3,320 个文件、254 个子目录**已迁移到 D `tools/local/python/cpython-3.12.13-windows-x86_64-none`；所有文件逐一校验 SHA256，迁移后再次全部校验通过。原精确 C 版本路径是指向该 D 目录的 junction；已有无版本号的 C junction 继续兼容既有项目。D `.cache/storage-migration/python-verified-copy` 还保留了验证过的完整 Python 副本。
- 批量递归移除 C 源目录并建 junction 的命令曾被自动审批拒绝，工具只提供 `blocked by policy`，没有更详细理由；被拒命令未执行。随后范围明确的原生 `Move-Item` 已完成小型 Python 项迁移；之后没有继续迁移 C uv 缓存，也没有修改分页文件、Codex、其他 Python 版本或用户全局环境变量。
- `.venv/pyvenv.cfg` 的 `home` 已改为 D 实体路径。仅修改 `home` 时 uv 的 Windows 启动器仍引用旧 C 路径，因此用 `uv venv --allow-existing --python <D实体解释器> --offline --no-python-downloads .venv` 更新启动器，保留原有 `site-packages`。原配置与两个启动器备份在 D `.cache/storage-migration`。
- 验证确认 `.venv` 的 `sys.base_prefix` 与 `sys._base_executable` 原始值均为 D 实体路径；FastAPI 0.142.2、SQLAlchemy 2.0.54、Frida 17.22.2、UnityPy 1.25.4 导入成功。`uv cache dir` 返回 D 工作空间 `.cache/uv`。
- `tools/env.ps1` 只设置当前进程及其子进程的开发环境：uv/Pip/PyInstaller/JADX 缓存、Pytest 临时目录、TEMP/TMP/TMPDIR、Python 字节码缓存均放在工作空间。运行开发命令前加载该脚本；未修改注册表或用户/系统环境变量。

C 盘迁移前快照空闲 **43,244,146,688** 字节；15:14 的空闲为 **43,300,384,768** 字节，观察净增 **56,238,080** 字节（约 53.63 MiB）。这是同时存在系统后台写入的净变化，不能等同于 Python 的逻辑大小。分页文件仍为 10,737,418,240 字节，最后写入时间仍为 14:52:07。

完整复制校验清单、SHA256、运行环境输出和状态记录保存在 `.cache/storage-migration`；审计 JSON 的原始目录统计仍保留迁移前快照。

### 回退方式（未执行）

如需回退 Python，先停止使用该解释器的进程，核实 C 版本路径确为指向上述 D 实体目录的 junction。仅移除 junction 节点，**不得递归删除 D 目标**；从保留的验证副本恢复到原精确 C 版本路径，再恢复 `.cache/storage-migration/pyvenv.cfg.before` 和两个 `.before.exe` 启动器到 `.venv`，重新验证解释器与依赖。现有无版本号 C junction 仍指向原版本路径，无需改动其他解释器。

uv 的 C 原缓存未变更，不需回退。若只要恢复原项目 D 缓存，可以保留现有 D 复制缓存后，将 `.cache/uv-project-before-migration-20261007` 恢复为 `.cache/uv`；两份缓存均不含应删除的用户存档。当前进程环境由 `tools/env.ps1` 设置，关闭开发终端后即可回到原有全局环境。
