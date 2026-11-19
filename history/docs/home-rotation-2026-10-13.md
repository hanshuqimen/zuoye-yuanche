# 看板轮换与助理编辑

最新结论：A15 在普通单套外观助理保存与预设管理范围内已修复并实际验证。完整 794 项检查、原版保存/创建/重命名、正确 setCurrent 路径的应用/切回/删除，以及程序和模拟器冷启动保持通过。多套外观轮换、位置编辑、额外背景/主题解锁、特殊立绘和整个游戏的完整验收仍未完成。以下失败记录保留为阶段证据。

服装原生验收发现 A15：主页助理编辑页进入一半、按钮无效，日志出现 `HomeSecretaryChangeStateBean.get_displaySkin` 的 NullReferenceException。单位换装与服装购买已独立通过；此异常不属于购买事务失败。

## 原始依据

冻结国服官服 2.7.71/190 的 PlayerDataModel.charRotation 在 +0x1c0。元数据 JsonPropertyAttribute 明确 `PlayerCharRotation.currentPresetId` 的 JSON 名为 `current`、`presets` 为 `preset`。预设字段为 name/background/homeTheme/profile/profileSp/slots；slots 含 charId/skinId/skinSp。profile 是外观 ID，不能填干员实例 ID。

默认 native `HomeCharRotationViewModel.LoadData/RefreshData` 从 current 和非空 preset key 生成编辑参数。`HomeSecretaryChangeStateBean.LoadData` 在 presetInstId 为空时提前退出，不创建 cardGroup.Value，随后 get_displaySkin 解引用而失败。其 _LoadAllCards 还要求 preset 字典、对应 key 和非空 slots。添加空字典不会修复实际调用链。

本次有界读取只针对拥有客户端进程中冻结 ELF 的 file-backed text 页，核对测试实例及硬件身份，不读取玩家对象、匿名堆或认证数据。额外读取 48 KiB（含 4 KiB 重复页面），按索引范围线性解码；原始默认路径不能证明动态 Lua/hotfix 分支均相同。证据保留在 `.cache/rea-2026-10-13/home-secretary-contract/` 及 `.cache/client-metadata/home-*-20261013-loaded.*`。

| 默认 native 位置 | 已确认行为 |
|---|---|
| 0x3bdf258 | 打开助理编辑页时传入 displayPresetInstId |
| 0x3bdf7cc | 设置资料页助理，构造 CharRotationUpdatePresetRequest，flag=8 |
| 0x3bf6b70 | 保存助理轮换列表，flag=24（资料页助理 8 + 列表 16），同时发送 profile/profileInst/profileSp/slots |
| 0x3bdfdc8 | 应用预设，构造 CharRotationSetCurrentPresetRequest，只含 instId |
| 0x3bd07ac | 重命名构造更新请求，flag=1 |
| 0x3bcfca8 / 0x3bd0344 | 正在使用的配置不可删除；创建前检查预设数量上限 |

冻结 GameData 原始常量为预设上限 4、外观上限 20，默认角色/外观为阿米娅与其初始外观，背景和主题为罗德岛日间；名称取 defaultCRPresetName。没有使用 prefab 占位文本“这里是看板二”或“7/12”。2/4 的背景/主题标记与原始 enum 编码一致，尚未按真实编辑按钮分别验收。

## 实施与存档

新增 HomeRotation、HomePreset、HomePresetSlot 三类领域实体和 `0011_home_rotation` 迁移。账号隔离和配置/当前引用通过数据库外键保证。每个预设及每个排序外观单独持久化；初始化仅在建号或启动/候选恢复的写事务执行，syncData 不创建配置。

已有账号用真实 profile.secretary/secretary_skin 初始化一套非空预设，保留旧助理和单位穿戴。预设实例 ID 使用本地稳定随机 ID，并非官服实例 ID。新预设的默认外观、背景、主题及名称取匹配常量。默认引用和上限在打开数据库前验证，不从 UI 文案或历史截图推测。

新增四个严格请求适配：创建、删除、应用、更新。更新使用实际 flag 和 JsonProperty 名称，所有权、角色归属、精英化、数量、重复外观与当前引用检查通过后统一提交；错误回滚名称、列表、助理、revision 和收据。应用当前预设时同步 status 的秘书字段，单位换装不受影响。旧 changeSecretary 兼容请求只更改当前预设为一套外观，与新版轮换编辑请求分开。

背景/主题当前只拥有既有默认项；未获得的背景、主题拒绝。特殊动态立绘、升变模板权限仍明确未实现。名称 64 字符和请求容量 1,024 是本地存储/输入保护上限，不宣称官服服务端文本规则。正式数量取冻结 GameData。

## 验证状态

专项 39 项通过，包括 23 项新看板检查及 16 项既有外观检查。后续增加旧版备份候选初始化、超过外观上限和坏目录拒绝检查，完整 **787 项通过（141.58 秒）**、Ruff 零诊断。第一次全量运行因新增测试误用 cached_property.fget 失败，已修正夹具后完整重跑；没有把失败运行记作通过。原生验收正在执行。

源码原生首次复测已正常显示“未命名界面配置”和 1/1 助理，进入角色选择与外观选择，原有半初始化页面不再出现。实际 `/charRotation/updatePreset` 请求的字段和别名一致；profileSp、slots.skinSp 为 int，被严格 bool 以 422 拒绝。25 张玩法表及三个看板表均未改变，129 份保护输入保持，外键/数据库完整性通过。该失败截图和原测试库保留。

现仅兼容上述字段的严格 0/1 整数与 bool，其余值仍拒绝；整数和布尔的同义请求使用相同收据，不开放特殊立绘权限。新增七项回归，最新完整 **794 项通过（131.23 秒）**、Ruff 零诊断。修正后的新 EXE 与原生保存/重启尚待验收，以下边界保持。

完整原生编辑、请求路由实际名称、整数布尔编码、创建/应用/删除/重命名和新 EXE 重启仍须验证。当前不得将 A15 标为修复完成，或宣称全部看板功能、全部游戏功能无 bug。

第二阶段独立 EXE `20261013T045410.960848Z-53c906aa` 的 1,079 文件指纹通过。真实助理保存、创建和重命名均 200，原生配置页正确显示陈的头像、名称 TerraLocalQA 和 2/4 配置；源石保持 42。实际应用路径为 `POST /charRotation/setCurrent`，此前较长名称未注册而返回 501，原助理和当前引用保持。现已按实测路径修正，旧名称不再作为未经验证的别名提供。

该运行未计为完整通过；应用失败后客户端返回登录页，删除未执行。25 张玩法表保持，131 份保护输入未变，实际 EXE 将旧副本从 0010 迁移为 0011，数据库/外键完整性通过。截图、旧 EXE 和两套配置仍保留。只读客户端诊断未见原 get_displaySkin 空引用，但存在 SDK/更新阶段的 Java 异常类型，尚未逐条定位，不宣称全客户端零异常。

应用路由修正后完整 **794 项通过（147.65 秒）**、Ruff 零诊断；现用保留已保存助理和名称的新副本继续打包验收，不覆盖失败程序或测试库。

## 最终独立程序验收

新开发包 `20261013T052753.031903Z-c2b49f5c` 的 EXE SHA-256 为 `87c3f8e0e82fd714d3c55416057e652a7f124601735013d471bf16c6df1757e3`。1,079 文件在打包和停止验收后均匹配。174 个 Python 构建输入指纹为 `6ecc524edeca897ddc85f7e29e3daa5ae585aca50963dd4ce3bae5413f881158`；这是构建输入清单，不称重新逐行审阅全部源码。

本程序使用前次成功保存的独立副本，真实恢复陈的岁红霞、TerraLocalQA 名称和两套预设。应用默认阿米娅、切回陈均为 `/charRotation/setCurrent/200`，页面出现“主界面已更新”并准确改变应用标记。删除未使用预设为 `/charRotation/deletePreset/200`，数量变回 1，当前陈配置保持。正确程序此运行无失败路由；创建/保存/重命名沿用前份 EXE 的真实证据，其领域和请求适配代码没有随应用路由修正而改变，未将旧程序整体称为通过。

程序进程重启一次，并使测试模拟器冷启动。重新登录后原版主页显示陈岁红霞，编辑页保留 TerraLocalQA、应用中与 1/1 外观，源石仍为 42。完整看板表及助理在重启检查点保持，25 张跟踪玩法表相对本次基线不变，133 份保护输入保持，数据库与外键完整性通过。删除只影响新测试副本，旧失败库、旧程序和原实例保留。

实际验收与回读记录在 `.cache/home-rotation-final-native-2026-10-13/acceptance.json`，原生截图在同目录。该闭环通过不代表背景/主题获得、所有外观轮换、所有游戏系统或两小时零故障；SDK/更新阶段诊断仍须后续归因。测试服务与模拟器已停止。
