# 昨夜圆车

本地服务源码、存档工具与开发进度。当前源码检查点为 `89e3dee`（原始历史基线 `d40aee9`），项目的入口命令保留为 `terralocal`。

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

## Windows 修复和工作区迁移检查点

2026-11-19 Windows 包的备份恢复、UTF-8 管道、冷启重试及启动窗口备份已在合成存档实际验证，并进入本机新的独立发行目录。1,080 文件和 MIT 清单匹配，27 份旧 EXE 保留。用户指定的22个目录已完整迁入项目，所有新增开发及恢复文件限于工作区；旧私有仓库已按当次确认删除。完整玩法、原生客户端、断网和 HarmonyOS 验收仍未完成。

[Windows 验证范围](docs/windows-backup-release-2026-11-19.md) · [22目录迁移](docs/workspace-directory-move-2026-11-19.md)。发行物和本地数据不随源码仓库上传。

[新增历史包](history/source-updates-f7b08f8.bundle)及[摘要](history/source-updates-f7b08f8.json)在原始完整包基础上恢复674个源码文件和361次开发提交；不需要先应用旧增量：

```powershell
git -C restored-history fetch ../history/source-updates-f7b08f8.bundle codex/development
git -C restored-history merge --ff-only FETCH_HEAD
```

## 危机合约V2地图规则检查点

2026-11-20 危机合约V2节点、连接/互斥接纳与六维计分组件已实现。38项定向合成检查及Ruff通过，五实际地图配置和六组合成投影通过；四临时图空默认节点的首次过严校验已撤回，失败保留。仅验证规则组件，尚无新模式路由、玩家授予、战斗结算或原生可玩结论；完整服务端仍未完成。

[依据和反例](docs/crisis-contract-2026-11-19.md) · [合成验证摘要](validation/crisis-v2-map-rules-20261120.json)。

[本次历史增量](history/source-updates-a264118.bundle)只需原始完整包，不需要先应用旧增量；保留全部旧包和历史：

```powershell
git -C restored-history fetch ../history/source-updates-a264118.bundle codex/development
git -C restored-history merge --ff-only FETCH_HEAD
```

## 危机合约V2信息与存档检查点

2026-11-20 危机合约V2已接版本绑定的信息源、getInfo事务、0038账号/赛季/地图及current/nst同步。210个不同定向检查最新通过，包含旧行/回滚、认证、损坏缺表写入前拒绝、并发及恢复；独立20表首季五图包9次真实HTTPS、两进程退出0、冷启重试及新目录恢复通过。原配置/旧历史保持；日历为明确本地政策，原生、开战/结算、解锁/商店、其他赛季及新EXE仍未完成。

[实现与实际范围](docs/crisis-information-2026-11-20.md) · [本次验证摘要](validation/crisis-v2-information-20261120.json)。

[本次历史增量](history/source-updates-48e71eb.bundle)只需原始完整包，不需要先应用旧增量；保留全部旧包和历史：

```powershell
git -C restored-history fetch ../history/source-updates-48e71eb.bundle codex/development
git -C restored-history merge --ff-only FETCH_HEAD
```

## 危机合约V2战斗合同与研究工具检查点

2026-11-20 继续危机合约V2战斗合同：开战8个方法范围与结算5个默认方法经REA查询，三辅助Hotfix分支保护仍保留；五实际地图的stageId不在普通stage_table。新增自有研究配置工具，选择REA已有认证本机TCP并要求项目内短运行路径；原件/失败保留。两次public close的清理竞态分别记录，实际进程/目录随后消失；不称全流程无错误。游戏服务仍为48e71eb信息阶段，未新增战斗路由、原生、产品测试或EXE。

[依据与未完成项](docs/crisis-battle-contract-2026-11-20.md) · [研究结果摘要](validation/crisis-v2-battle-research-20261120.json)。

[本次历史增量](history/source-updates-e54cee2.bundle)只需原始完整包，不需先应用其他增量：

```powershell
git -C restored-history fetch ../history/source-updates-e54cee2.bundle codex/development
git -C restored-history merge --ff-only FETCH_HEAD
```

## 危机合约V2主结算合同及挑战条件

2026-11-20 取得主结算/地图/编队/缓存五个默认消费者的加载依据（2,960字节），确认runeCount为旧/当前两个数量，新增九字段响应模型。按匹配数据实现首季五图15项挑战条件，保留二选一、通关和源指纹门槛。221个不同定向检查的最新结果通过；本批无全量重跑、新战斗会话/发奖路由、原生游玩或新EXE。独立冻结包未改动，首季观察时已按绑定本地日历关闭，不能把条件覆盖当成当期可领取或完整模式。

[依据和实际支持范围](docs/crisis-battle-contract-2026-11-20.md) · [本批验证摘要](validation/crisis-v2-challenges-20261120.json)。

[本次历史增量](history/source-updates-c06199f.bundle)只需原始完整包：

```powershell
git -C restored-history fetch ../history/source-updates-c06199f.bundle codex/development
git -C restored-history merge --ff-only FETCH_HEAD
```

## 危机合约V2持久化开战会话

2026-11-20 新增危机合约0039内部持久化开战/上下文，绑定地图、版本、选择、编队及本地登录；普通结算、恢复和代理增加模式保护，修复同步非法编队槽位越界。本批291个不同定向用例最新记录通过，原失败保留；冻结首季五图各独立QA账号的三进程/82表恢复通过。QA使用显式历史时钟，首季观察时已关闭，未开放原生战斗路由、发奖或重建EXE。

[保存与实际验证范围](docs/crisis-battle-sessions-2026-11-20.md) · [验证摘要](validation/crisis-v2-battle-sessions-20261120.json)。

[本次历史增量](history/source-updates-4228e95.bundle)只需原始完整包：

```powershell
git -C restored-history fetch ../history/source-updates-4228e95.bundle codex/development
git -C restored-history merge --ff-only FETCH_HEAD
```

## 危机合约结算日志与只读绑定

2026-11-20 危机合约结算准备新增15个REA默认方法/9,712字节，确认日志调用链、符文完成及任务状态消费者。新增专用解码和自有保存/关卡/编队只读绑定，74个不同定向检查通过；冻结五图自造请求核对，82表保持。原生APK校验首次8秒超时及后续三页成功捕获分别保留；两REA会话关闭/退出0，index1已停且index0/宿主保存保持。本批未分类通关、写入进度/奖励、开放原生路由或重建EXE。

[依据、失败和支持边界](docs/crisis-finish-logs-2026-11-20.md) · [验证摘要](validation/crisis-v2-finish-logs-20261120.json)。

[本次历史增量](history/source-updates-8dcbcd5.bundle)只需原始完整包：

```powershell
git -C restored-history fetch ../history/source-updates-8dcbcd5.bundle codex/development
git -C restored-history merge --ff-only FETCH_HEAD
```

## 危机合约任务事务组件

2026-11-21 危机合约新增绑定地图的任务进度事务组件：符文/挑战、指标集和同场宝藏，保留领取态、空0/0单列。89个不同当前定向检查通过；冻结首季五图人工给定clear，82表冷启/新目录恢复一致且现用/源数据保持。REA两个方法中一个588字节正常路径完成，另一个超时保留；公共关闭/退出0。本批不分类原生通关，不写分数/评论，不领奖或结束战斗，原生路由与完整成品仍未完成。

[规则、验证和失败](docs/crisis-objectives-2026-11-21.md) · [验证摘要](validation/crisis-v2-objectives-20261121.json)。

[本次历史增量](history/source-updates-af686f3.bundle)只需原始完整包：

```powershell
git -C restored-history fetch ../history/source-updates-af686f3.bundle codex/development
git -C restored-history merge --ff-only FETCH_HEAD
```

## 危机合约失败与退出回执

2026-11-21 危机合约新增失败/退出版本化回执、终态重试与只读保存预检，任务组件拒绝终态再写进度。102个不同当前定向检查最新通过；冻结五图人工加密请求、三实际进程和82表冷启/新恢复一致，现用/源数据保持。三个新REA方法3048字节补写入器/构造器及ListDict对象格式，先前超时保留，公共关闭/退出0。通关候选仍明确拒绝，分数/全部评论、领取、原生路由及成熟成品尚未完成，无新EXE。

[结果、依据和支持范围](docs/crisis-exits-2026-11-21.md) · [验证摘要](validation/crisis-v2-exits-20261121.json)。

[本次历史增量](history/source-updates-ab461ec.bundle)只需原始完整包：

```powershell
git -C restored-history fetch ../history/source-updates-ab461ec.bundle codex/development
git -C restored-history merge --ff-only FETCH_HEAD
```

## 危机合约快照计数与评语条件

2026-11-21 危机合约快照计数已核对应extraBattleInfo，新增选择性计数、首季22条/8种评语条件及只读通关准备。169个不同当前定向检查通过，冻结五图人工请求可计算资格，82表不变、现用和源数据保持。受控读取4代码页及1只读偏移页共20480字节；三个新REA方法2896字节，公共关闭/退出0。实际原生计数格式未观察；一条评语导入110与社区220差异保留。尚未接原子通关、分数/历史、领取或原生路由，未重建EXE，完整成品仍未完成。

[结果、依据和支持范围](docs/crisis-comment-counters-2026-11-21.md) · [验证摘要](validation/crisis-v2-comment-counters-20261121.json)。

[本次历史增量](history/source-updates-1e07741.bundle)只需原始完整包：

```powershell
git -C restored-history fetch ../history/source-updates-1e07741.bundle codex/development
git -C restored-history merge --ff-only FETCH_HEAD
```

## 危机合约原子本地通关

2026-11-21 危机合约已接原子本地通关纪录、共享任务投影、评语、终态回执和只读重放。197个不同当前定向检查最新通过；冻结五图三实际进程退出0，82表冷启/新恢复全行一致，源和现用保持。本批无新模拟器/REA读取。纪录合并为显式本地策略，不冒称恢复官方后端；原生路由/九字段映射、领取/解锁、原始回放、资料差异及成熟成品仍待完成，无新EXE。

[结果、依据及未完成范围](docs/crisis-atomic-clears-2026-11-21.md) · [验证摘要](validation/crisis-v2-atomic-clears-20261121.json)。

[本次历史增量](history/source-updates-adefbe5.bundle)只需原始完整包：

```powershell
git -C restored-history fetch ../history/source-updates-adefbe5.bundle codex/development
git -C restored-history merge --ff-only FETCH_HEAD
```

## 危机合约原生战斗路由

2026-11-21 危机合约原生开战/结算路由、九字段本地展示及持久首次响应已接。196当前定向检查通过（22新/174关联）；冻结五图40真实HTTPS、三服务退出0，82表冷启/新恢复一致。新增8KiB读取和9方法1980字节REA；真实数据否定packedRune.key，按原版id及147条证据纠正，失败副本保留。原版客户端画面、领取/解锁/商店/原始回放及成熟成品仍待验，无新EXE。

[结果、依据及纠正](docs/crisis-native-battles-2026-11-21.md) · [验证摘要](validation/crisis-v2-native-battles-20261121.json)。

[本次历史增量](history/source-updates-ec9f1a6.bundle)只需原始完整包：

```powershell
git -C restored-history fetch ../history/source-updates-ec9f1a6.bundle codex/development
git -C restored-history merge --ff-only FETCH_HEAD
```

## 危机合约本地功能与原版联调

2026-11-26 危机合约独立配置、本地领奖/符文/显式商店/战报及默认关闭日志归档已整理。原版已到信息/主地图导览，79请求全200但0新战斗；旧赛季entry/atlas在当前清单和APK缺失，未冒充补齐。按原版反例修复符文提前解锁，需关联图全部任务；61相关检查及首季六符文30次HTTPS/冷重试通过。REA1140字节确认confirmMissions，close身份检查失败但后续进程/目录实际已无；旧失败保持。官方领奖/商店、原版战斗与完整成品仍未完成，无新EXE。

[原版联调和修复](docs/crisis-native-client-2026-11-26.md) · [本地功能边界](docs/crisis-local-extras-2026-11-25.md) · [验证摘要](validation/crisis-v2-native-client-20261126.json)。

[本次完整历史增量](history/source-updates-8fe508c.bundle)只需原始d40完整包，旧包和精选回滚分支保留：

```powershell
git -C restored-history fetch ../history/source-updates-8fe508c.bundle codex/development
git -C restored-history merge --ff-only FETCH_HEAD
```

## 原版危机合约宝藏领取

2026-11-26 原版危机合约宝藏批量领取、账号/版本绑定业务回执及恢复准入已接。89相关检查和冻结首季三宝藏18HTTPS/冷启/新恢复通过，资格预置，不是自然通关。原版实际一次家具获得弹窗和任务1/14，库存1，冷会话30请求全200、0新战斗；正常收尾恢复两回调/index1关闭/源现用保持。REA默认任务类型0/1/2及rewards消费者已核，首timeout/误补查地址/包装器1保留，不伪称public close成功。符文组/挑战币、旧季图集、原版战斗/商店/回放和完整交付尚缺，无新EXE。

[本批实现和原版证据](docs/crisis-native-missions-2026-11-26.md) · [验证摘要](validation/crisis-v2-native-missions-20261126.json)。

[本次完整历史增量](history/source-updates-f3fc441.bundle)仅需原始d40完整包，保留所有旧包与分支：

```powershell
git -C restored-history fetch ../history/source-updates-f3fc441.bundle codex/development
git -C restored-history merge --ff-only FETCH_HEAD
```

## 原版危机合约符文组与挑战领奖

2026-11-26 原版危机合约符文组0/挑战1及混合宝藏2批次已接，密封回执核账，旧宝藏回执保持。18新增/107不同当前检查、冻结首季五图9预置QA方案162HTTPS、三次有序服务组/冷启/新目录恢复通过。18处12916字节REA消费者支持真实商店路由、限时物品显示和余额字段依据；到期发奖为已明确的本地策略。原版任务币弹窗、原生商店/购买、未知season.coin、其他赛季、旧季图集、新EXE与完整交付仍未完成。包含目录迁移当前回读及前批公开恢复/换行纠正记录，保留失败和全部旧历史。

[本批实现和依据](docs/crisis-native-coins-2026-11-26.md) · [验证摘要](validation/crisis-v2-coin-missions-20261126.json)。

[本次完整历史增量](history/source-updates-89e3dee.bundle)仅需原始d40完整包，保留所有旧包与分支：

```powershell
git -C restored-history fetch ../history/source-updates-89e3dee.bundle codex/development
git -C restored-history merge --ff-only FETCH_HEAD
```
