# 项目：Arknights Local Server / 高还原度本地单机服务器

你现在是一名资深游戏后端工程师、Python/Rust 服务端工程师、Unity 网络协议分析工程师、Android 调试工程师和软件架构师。

你的任务是在我的计算机上开发一个面向**个人、非商业、本地使用**的《明日方舟》兼容服务器，使我能够：

- 在 Windows 主机上运行服务器；
- 使用我自己合法取得的《明日方舟》客户端连接；
- 手机主要考虑 HarmonyOS 设备；
- 如果 HarmonyOS 当前环境暂时不适合调试，则必须首先保证 Android 模拟器环境完整可用；
- 最终手机与电脑连接同一局域网时，可以像连接正常游戏服务器一样进入游戏；
- 尽可能让玩家的**主观游玩体验、交互流程、界面行为和游戏状态变化与正常《明日方舟》一致**。

这里的“高还原度”不是简单做到：

“能进主页、资源无限、能抽卡。”

而是要做到：

启动 → 登录 → 公告/签到 → 主界面 → 理智 → 邮件 → 任务 → 干员 → 编队 → 仓库 → 商店 → 寻访 → 公开招募 → 好友/助战 → 基建 → 关卡 → 战斗结算 → 活动 → 肉鸽等流程在客户端中表现自然，尽量不出现：

- 404；
- 空白页面；
- 网络错误；
- 无限 Loading；
- 被踢回登录界面；
- 明显不符合官服逻辑的数据；
- 点进去之后没有任何实现的菜单；
- 后端状态与 UI 状态不一致。

项目代号暂定：

`TerraLocal`

如仓库已经存在，则不要擅自重命名。

---

# 一、第一原则：不要从零盲写

在开始编码之前，你必须首先研究现有项目。

至少研究下面这些参考实现。

## 1. OpenDoctoratePy-EX-Public

这是最重要的直接参考之一。

项目：

[OpenDoctoratePy-EX-Public](https://github.com/jiellll1219/OpenDoctoratePy-EX-Public?utm_source=chatgpt.com)

重点研究：

- server 目录结构；
- API 路由；
- syncData；
- config；
- memory cache；
- 寻访；
- 好友助战；
- 活动；
- 签到；
- 商店；
- 肉鸽；
- 时间系统；
- 客户端兼容策略；
- GameData 加载方式。

该项目 README 明确提出其长期目标是实现类似 SPT-AKI 的单人本地服务。

注意：

该 GitHub 仓库在 2026-02-22 已归档。

因此：

**把它当协议、数据结构和历史实现参考，而不要无脑直接复制整个仓库继续堆代码。**

如果复制 GPLv3 项目的代码，则必须明确处理 GPLv3 的衍生作品许可要求。

优先采用：

“理解行为 → 写兼容测试 → clean-room 重实现”

而非：

“复制所有代码 → 修改变量名”。

---

## 2. OpenDoctoratePy

DoctoratePy 系列的另一个重要实现：

[OpenDoctoratePy](https://github.com/baiqilingnai/OpenDoctoratePy?utm_source=chatgpt.com)

研究：

- 基础登录过程；
- 本地服务端结构；
- Frida 辅助启动方式；
- syncData 构造；
- config；
- 干员自定义；
- 危机合约等历史功能。

用于理解 DoctoratePy 系服务端的演化过程。

---

## 3. DoctoratePy

历史项目。

如果仓库仍可访问：

`nonobject14514/DoctoratePy`

用途：

研究早期最小实现和基础协议设计。

不要把旧接口直接视为当前客户端标准。

---

## 4. Darknights-server

项目：

[Darknights-server](https://github.com/LewisGet/__Darknights-server?utm_source=chatgpt.com)

重点理解其架构思想：

Client
→ HTTP(S) interception/proxy
→ Nginx / Router
→ Application Server
→ Database

以及：

- 登录；
- 寻访；
- 战斗；
- 客户端—服务器交互拆分。

它是理解“客户端需要服务器做什么”的参考，而不是最终技术栈模板。

---

## 5. KCN_ArknightsServer

项目：

[KCN_ArknightsServer](https://github.com/JDDKCN/KCN_ArknightsServer?utm_source=chatgpt.com)

它对我们的价值主要在于：

**最终用户体验。**

研究：

- Windows 一键启动；
- IP 配置；
- 手机局域网访问；
- 服务端管理；
- GM；
- 简化部署。

最终 TerraLocal 的部署体验至少不能比这一类“一键端”更复杂。

理想情况：

```text
双击 TerraLocal.exe

Server started

Local:
127.0.0.1:8443

LAN:
192.168.1.100:8443

Client helper:
Ready
```

然后手机可以连接。

---

## 6. LocalArknights

项目：

[LocalArknights](https://github.com/sanhaiwangxing/LocalArknights?utm_source=chatgpt.com)

这个项目虽然客户端版本很旧，但实现过：

- 好友；
- 助战；
- 公开招募；
- 寻访；
- 干员养成；
- 商店；
- 战斗；
- 掉落；
- 基建。

研究重点：

**一个完整单机环境需要保存哪些状态。**

不要局限于 API endpoint。

真正重要的是：

```text
PlayerState
WorldState
InventoryState
OperatorState
MissionState
BuildingState
StageState
GachaState
EventState
FriendState
```

之间如何持续一致。

---

# 二、协议分析的重要参考

## Arknights-RE

项目：

[Arknights-RE](https://github.com/djpadbit/Arknights-RE?utm_source=chatgpt.com)

这是非常重要的现代参考资料。

重点研究：

- 当前客户端请求；
- MITM 环境；
- Android Emulator；
- Frida；
- HTTPS；
- 请求/响应格式；
- 登录；
- syncData；
- battle records；
- telemetry；
- 数据加解密。

但是必须遵守以下原则：

仅用于：

- 我自己的客户端；
- 我的模拟器；
- 我的设备；
- 本地研究；
- 协议兼容。

不要构建：

- 大规模官方服务器抓取器；
- 自动化官服账号操作平台；
- 第三方流量窃听工具。

---

## rhine

项目：

[rhine](https://github.com/kyoukaya/rhine?utm_source=chatgpt.com)

这是模块化游戏流量处理框架。

重点研究：

- packet logger；
- game state mirror；
- authentication 后状态处理；
- 请求/响应观察；
- 不同模块解耦。

TerraLocal 应借鉴一个非常重要的思想：

**协议观察工具与真正的游戏服务器必须分离。**

例如：

```text
tools/
    traffic_recorder/
    protocol_diff/
    fixture_builder/

server/
    api/
    domain/
    persistence/
```

服务器运行时不应该依赖抓包工具。

---

## ArkPRTS

项目：

[ArkPRTS](https://github.com/ashleney/ArkPRTS?utm_source=chatgpt.com)

研究：

- 数据模型；
- 玩家数据结构；
- API wrapper；
- server region 差异；
- 请求模型；
- pydantic model；
- 原始数据与类型数据之间的映射。

不要使用它去批量操作官服账号。

将其作为协议/模型参考。

---

# 三、GameData / 静态数据资料

## ArknightsGameData

[ArknightsGameData](https://github.com/Kengxxiao/ArknightsGameData?utm_source=chatgpt.com)

这是项目非常重要的数据来源参考。

服务器逻辑必须尽量做到：

**GameData-driven**

而不是：

```python
if operator == "char_xxx":
    ...
```

大量硬编码。

例如：

```text
character_table
skill_table
item_table
stage_table
zone_table
mission_table
building_data
gacha_table
shop_client_table
uniequip_table
activity_table
story_table
enemy_database
```

应该经过：

```text
GameData Importer
        ↓
Normalized Data Model
        ↓
Versioned Data Cache
        ↓
Gameplay Services
```

服务器本身不得把大量游戏表内容直接写死在源码中。

同时：

不要把未经授权的完整游戏资源直接打包进公开发布物。

允许用户自行提供数据目录。

---

## OpenArknightsFBS

[OpenArknightsFBS](https://github.com/MooncellWiki/OpenArknightsFBS?utm_source=chatgpt.com)

用于研究当前客户端部分 FlatBuffers 数据结构。

服务器必须设计：

```text
GameDataVersion
GameDataAdapter
```

而不是假设所有客户端版本的数据 Schema 永远不变。

例如：

```python
class GameDataAdapter:
    def load_character_table(...)
    def load_stage_table(...)
    def load_activity_table(...)
```

不同版本可拥有不同 adapter。

---

# 四、网络调试参考

mitmproxy 官方资料：

[mitmproxy 工作原理](https://docs.mitmproxy.org/stable/concepts/howmitmproxyworks/?utm_source=chatgpt.com)

证书：

[mitmproxy Certificates](https://docs.mitmproxy.org/stable/concepts/certificates/?utm_source=chatgpt.com)

Android Emulator 系统 CA：

[mitmproxy Android System CA 指南](https://docs.mitmproxy.org/stable/howto/install-system-trusted-ca-android/?utm_source=chatgpt.com)

这些工具仅允许用于：

**本地测试设备与本人拥有/控制的客户端环境。**

开发阶段优先在 Android 模拟器中分析。

不要一开始就在 HarmonyOS 真机上调协议。

---

# 五、核心产品定义

TerraLocal 本质上不是：

“一个修改器。”

也不是：

“一个无限资源作弊器。”

而应该被设计成：

> 一个本地运行的 Arknights Server Emulator。

客户端应该尽可能相信：

```text
它正在连接一个正常服务器。
```

因此真正需要模拟的是：

```text
Server Semantics
```

而不仅是：

```text
HTTP 200
```

---

# 六、体验目标

玩家第一次启动时应该经历：

```text
启动客户端

↓

正常进入登录流程

↓

连接 TerraLocal

↓

登录本地 Doctor 账号

↓

加载游戏数据

↓

进入主页

↓

所有主要按钮正常显示

↓

进入每个主要系统不会报错

↓

游戏行为产生的数据被可靠保存

↓

退出

↓

重新登录

↓

游戏状态完整恢复
```

任何“看起来能打开、实际上没有状态”的实现都不能算完成。

---

# 七、服务器架构

优先使用：

Python 3.12+

推荐：

FastAPI
Pydantic
SQLAlchemy
SQLite

开发阶段默认 SQLite。

结构：

```text
terralocal/

    server/

        main.py

        api/
            auth/
            account/
            user/
            char/
            squad/
            inventory/
            stage/
            battle/
            gacha/
            recruit/
            building/
            shop/
            social/
            mission/
            mail/
            event/
            roguelike/
            config/

        domain/

            account/
            operator/
            inventory/
            battle/
            progression/
            building/
            gacha/
            shop/
            mission/
            event/

        services/

        persistence/

        protocol/

        gamedata/

        compatibility/

    admin/

    launcher/

    client_helper/

    tools/

        protocol_recorder/
        fixture_builder/
        protocol_diff/
        gamedata_importer/

    tests/

        unit/
        integration/
        protocol/
        snapshots/
        regression/

    docs/

        architecture.md
        protocol.md
        compatibility.md
        gamedata.md
        harmonyos.md
        reverse-engineering-notes.md
        roadmap.md

    data/

    config/

    logs/
```

如果研究现有项目后发现其他技术栈显著优于 FastAPI，可以修改方案，但必须先写 ADR：

```text
docs/adr/xxxx-*.md
```

说明理由。

---

# 八、数据库设计

禁止只有一个：

```text
syncData.json
```

然后每次整个 JSON 覆写。

那可以作为兼容输出，却不能作为长期内部架构。

至少建立以下实体：

```text
Account
PlayerProfile

Currency
InventoryItem

Operator
OperatorSkill
OperatorModule

Squad

StageProgress
StageReplay
BattleSession

MissionProgress

RecruitSlot

GachaHistory
GachaPity

Building
BuildingRoom
BuildingOperatorAssignment

Mail

Friend
SupportUnit

ShopState
PurchaseHistory

EventProgress

RoguelikeRun

ServerClock
```

所有关键操作要求事务。

例如：

```text
购买商品

check currency
↓
deduct currency
↓
grant item
↓
update shop stock
↓
write purchase history
↓
commit
```

任何一步失败：

rollback。

---

# 九、syncData

这是最重要的模块之一。

设计一个：

```text
SyncDataAssembler
```

内部状态不能依赖一个巨大 JSON。

应该：

```text
Database
   ↓
Domain Models
   ↓
SyncDataAssembler
   ↓
Client-compatible response
```

必须建立 snapshot tests。

例如：

```text
tests/snapshots/syncdata/
```

每次新增系统后：

确保没有破坏客户端依赖字段。

---

# 十、服务端虚拟时钟

实现：

```text
ServerClock
```

支持：

```text
realtime
fixed
offset
```

例如：

```text
realtime

2024-01-01 04:00

official_event_simulation
```

用途：

- 旧活动；
- 旧卡池；
- 签到；
- 商店刷新；
- 日常任务；
- 周常任务；
- 理智恢复；
- 基建生产。

所有业务代码不得直接大量调用：

```python
time.time()
datetime.now()
```

统一：

```python
ServerClock.now()
```

---

# 十一、登录系统

本地服务器不需要真实短信。

设计：

```text
Local Account
```

例如：

```text
Doctor
password optional
```

默认提供：

```text
快速登录
```

目标是：

用户看到的登录体验合理，但绝不连接真实支付、真实短信或者真实认证服务。

保存多个本地存档：

```text
Doctor 1
Doctor 2
Test Account
```

---

# 十二、玩家初始状态

提供三种 preset：

```text
Vanilla
Progressed
Sandbox
```

Vanilla：

尽量接近新账号。

Progressed：

拥有合理的中后期账号状态。

Sandbox：

所有干员 / 大量资源 / 调试用途。

不要让“无限资源”成为唯一模式。

因为我要测试：

**真实游戏进度。**

---

# 十三、干员系统

必须正确支持：

- 获得干员；
- 等级；
- 精英化；
- 潜能；
- 技能等级；
- 专精；
- 信赖；
- 模组；
- 皮肤；
- 锁定；
- 编队；
- 助战。

所有限制尽量来源于 GameData。

例如：

```text
最大等级
精英条件
升级消耗
技能材料
专精材料
模组解锁
```

不要硬编码。

---

# 十四、寻访系统

实现真实状态机。

包括：

```text
banner
single pull
ten pull
history
currency consumption
pity
guarantee
duplicate conversion
new operator flag
```

支持：

```text
Standard
Limited
Kernel
Custom
```

抽卡结果必须：

1. 扣资源；
2. 生成结果；
3. 更新干员；
4. 重复干员处理；
5. 更新历史；
6. 更新 pity；
7. 返回客户端响应。

要求 deterministic test：

```python
seed = 12345
```

可以复现结果。

GM 可以设置 RNG seed。

---

# 十五、公开招募

实现：

- 4 个招募槽；
- tag；
- 时间；
- 刷新；
- 加急许可；
- tag → pool 筛选；
- 结果生成；
- 状态保存。

---

# 十六、战斗流程

这是项目的 P0 功能。

实现明确的：

```text
BattleSession
```

状态：

```text
CREATED
STARTED
FINISHED
ABORTED
```

正常流程：

```text
stage start

↓

validate stamina

↓

consume stamina / create battle reservation

↓

client battle

↓

battle finish

↓

validate result

↓

calculate reward

↓

update stage progress

↓

update missions

↓

grant items

↓

save replay if applicable

↓

response
```

不要为了“像官服”而伪造根本不存在的服务端战斗模拟。

如果原客户端本身承担战斗表现和大部分计算：

就保留客户端职责。

服务端重点保证：

- start；
- finish；
- progression；
- drop；
- replay metadata；
- stamina；
- mission；
- first-clear reward

正确。

---

# 十七、关卡系统

支持：

- 主线；
- 资源本；
- 芯片本；
- 剿灭；
- 活动关；
- Side Story；
- Intermezzi。

需要：

```text
StageRepository
StageUnlockService
StageDropService
StageProgressService
```

掉落：

支持：

```text
official-like
custom
guaranteed
debug
```

模式。

---

# 十八、理智

必须模拟：

```text
current sanity
max sanity
last recovery timestamp
recovery interval
overflow rules
sanity items
```

不要每次读取固定 135。

玩家退出几个小时后重新登录：

应该得到正确恢复后的理智。

---

# 十九、任务

实现：

```text
Daily
Weekly
Campaign
Event
Achievement
```

采用：

```text
Event Bus
```

例如：

```text
BattleFinished
OperatorLeveled
RecruitCompleted
ShopPurchased
BuildingCollected
```

任务系统监听事件更新。

避免每个 API endpoint 手工维护几十个 mission。

---

# 二十、基建

这是最容易被低估的系统之一。

不能只让 UI 能打开。

必须实现：

- 房间；
- 升级；
- 干员入住；
- 心情；
- 制造；
- 贸易；
- 发电站；
- 会客室；
- 办公室；
- 训练室；
- 宿舍。

所有时间相关逻辑：

lazy evaluation。

即：

不需要服务器每秒 tick。

例如玩家 8 小时后上线：

根据：

```text
start_time
current_time
production_rate
```

一次计算产出。

---

# 二十一、商店

实现本地虚拟商店。

支持：

- 信用商店；
- 绿票；
- 黄票；
- 活动商店；
- 家具；
- 皮肤；
- 常规资源。

严禁：

接入真实支付。

所谓“充值”仅能作为：

```text
GM grant currency
local simulated purchase
```

不能触发或伪造现实支付交易。

---

# 二十二、好友与助战

因为这是单机服务器：

好友系统可以有两种模式。

真实本地账号：

```text
Doctor A
Doctor B
```

互为好友。

以及：

```text
Synthetic NPC
```

本地生成虚拟好友。

NPC 要拥有：

- 名称；
- 等级；
- 头像；
- 签名；
- 助战干员；
- 上线时间。

这样玩家在好友界面不会觉得：

“私服完全是死的。”

---

# 二十三、邮件

建立 MailService。

支持：

- 系统邮件；
- 奖励附件；
- 已读；
- 领取；
- 一键领取；
- 过期时间。

GM 面板允许发送：

```text
Welcome mail
Event compensation
Custom mail
```

---

# 二十四、公告与活动

玩家进入游戏时：

可以显示正常的本地公告。

提供：

```text
AnnouncementService
```

管理员可以添加：

标题
正文
时间
banner
priority

活动系统采用：

```text
EventDefinition
+
EventState
```

不要给每个活动写巨大的：

```python
if event_id == ...
```

---

# 二十五、肉鸽

肉鸽复杂度极高。

放到 P2/P3。

架构首先支持：

```text
RogueRun
RogueNode
RogueInventory
RogueRecruit
RogueRelic
RogueEncounter
RogueBattle
```

优先做到：

“完整跑完一次”

再追求：

“所有主题全部兼容”。

可以重点参考 TerraPS 与 OpenDoctoratePy-EX 的历史实现思路。

TerraPS：

[TerraPS](https://github.com/DoctorateRS/TerraPS?utm_source=chatgpt.com)

它虽然已归档，但实现/探索过：

- roguelike；
- sandbox；
- tower

相关功能。

---

# 二十六、GM / 管理面板

提供 Web UI：

```text
http://127.0.0.1:<admin-port>
```

功能：

Dashboard

Accounts

Operators

Inventory

Stages

Gacha

Mail

Events

Server Time

Logs

Backup

Settings

例如：

```text
Grant item
Grant operator
Set level
Unlock stages
Set sanity
Set currency
Send mail
Select banner
Change server time
```

所有操作写入：

```text
audit_log
```

---

# 二十七、Launcher

Windows 用户不能被要求：

```text
开 Python
开数据库
开 Redis
开 nginx
开 mitmproxy
开 5 个 cmd
```

最终必须：

```text
TerraLocal.exe
```

启动。

Launcher：

检测：

- 端口；
- 数据库；
- GameData；
- IP；
- 服务状态。

显示：

```text
Server: Running

Local address:
127.0.0.1

LAN address:
192.168.x.x

Admin:
http://127.0.0.1:xxxx
```

---

# 二十八、HarmonyOS 手机支持

不要一开始针对 HarmonyOS 写全新游戏客户端。

我们的策略是：

## Path A

如果目标 HarmonyOS 环境可以运行 Android APK / 兼容环境：

使用 Android 客户端。

测试：

```text
安装
启动
联网
局域网访问
证书
DNS
代理
```

## Path B

如果真机不方便：

Android Emulator 首先成为官方开发测试平台。

必须保证：

```text
Windows Server
+
Android Emulator
```

100% 工作。

## Path C

以后再评估 HarmonyOS Native 客户端适配。

这不是 MVP。

---

# 二十九、客户端连接辅助工具

设计：

```text
client_helper
```

用于：

- 显示服务器 IP；
- 生成配置；
- 测试 TCP；
- 测试 HTTP；
- 测试 HTTPS；
- 测试 DNS；
- 检查客户端能否到达服务端。

不要要求普通用户理解网络协议。

例如：

```text
[✓] Server reachable
[✓] API reachable
[✓] GameData ready
[✓] Client route ready
```

---

# 三十、协议研究方式

如果现有文档无法解释客户端行为：

使用：

```text
black-box differential analysis
```

流程：

```text
操作 A
↓
记录 request
↓
记录 response
↓
改变一个变量
↓
再次操作
↓
diff
↓
推断字段含义
```

例如：

```text
Level operator 1 → 2
```

记录前后：

```text
request
response
syncData
inventory
operator state
```

然后建立：

```text
protocol fixture
```

严禁仅凭猜测实现字段。

---

# 三十一、协议 Fixture

目录：

```text
tests/protocol/fixtures/
```

保存脱敏结构：

```text
route
method
request schema
response schema
semantic notes
```

不要提交：

- 官方账号 token；
- 用户 credential；
- 私人 UID；
- 完整未脱敏流量；
- 密钥。

---

# 三十二、Protocol Compatibility Layer

API handler 不要直接写业务逻辑。

例如：

```text
HTTP Request

↓

Protocol Adapter

↓

Command

↓

Domain Service

↓

Result

↓

Protocol Adapter

↓

HTTP Response
```

这样客户端版本变化时：

主要修改：

```text
protocol/
compatibility/
```

而不是整个服务器。

---

# 三十三、客户端版本策略

禁止目标写成：

“永远支持最新版。”

第一阶段：

**锁定一个具体客户端版本。**

建立：

```text
ClientCompatibilityProfile
```

包括：

```text
client_version
resource_version
api_version
gamedata_version
supported_features
```

启动时输出：

```text
Supported Client:
CN Android x.x.xx
```

之后再添加：

```text
CN Android version B
```

不要为了新客户端把旧客户端支持弄坏。

---

# 三十四、GameData Importer

提供：

```text
terralocal gamedata import <folder>
```

扫描用户自己提供的：

```text
excel/
levels/
```

生成：

```text
data/cache/
```

并输出：

```text
characters: xxxx
items: xxxx
stages: xxxx
skills: xxxx
activities: xxxx
```

同时做 schema validation。

---

# 三十五、版本差异检测

建立：

```text
gamedata diff
```

例如：

```text
character_table:
 + 6 entries
 - 0 entries
 schema changed: false

activity_table:
 schema changed: true
```

版本升级时，首先跑 diff。

---

# 三十六、日志

结构化日志：

```text
timestamp
request_id
account_id
route
latency
result
```

开发模式：

DEBUG。

正常模式：

INFO。

不要打印：

token/password。

---

# 三十七、Debug Overlay

Admin 面板增加：

```text
Recent Client Requests
```

显示：

```text
POST /account/syncData       200  42ms
POST /quest/battleStart      200  8ms
POST /quest/battleFinish     200  16ms
GET  /shop/getShop           404
```

任何：

```text
404
500
schema mismatch
```

醒目标记。

我们的长期目标之一是：

**正常游戏过程中未知路由 = 0。**

---

# 三十八、Unknown Route Recorder

实现：

```text
UnknownRouteRecorder
```

当客户端访问未实现 endpoint：

记录：

```text
route
method
headers schema
body schema
timestamp
client version
```

开发模式可以返回：

安全的兼容响应。

但严禁默认：

```text
return {}
```

因为这样通常会隐藏 bug。

---

# 三十九、测试

测试优先级非常高。

至少：

```text
pytest
```

包含：

Unit Tests

Integration Tests

Protocol Snapshot Tests

Regression Tests

Database Tests

GameData Tests

例如：

```text
test_login
test_sync_data
test_single_gacha
test_ten_gacha
test_duplicate_operator
test_stage_first_clear
test_stage_repeat_clear
test_sanity_regeneration
test_shop_purchase
test_recruitment
test_base_production
test_save_reload
```

---

# 四十、Golden Playthrough

建立一个自动测试场景：

```text
Fresh Account

↓

Login

↓

Claim Mail

↓

Upgrade Operator

↓

Create Squad

↓

Start Stage

↓

Finish Stage

↓

Receive Drop

↓

Complete Mission

↓

Pull Gacha

↓

Enter Base

↓

Collect Production

↓

Logout

↓

Restart Server

↓

Login

↓

Verify Everything Persisted
```

这个测试必须长期保持通过。

---

# 四十一、性能目标

家庭电脑完全够用。

目标：

Idle：

< 150 MB RAM

Loaded GameData：

合理范围内 < 1 GB

普通 API：

P95 < 50 ms

syncData：

P95 < 300 ms

局域网游玩：

玩家不应明显感觉比真实服务器慢。

---

# 四十二、可靠性

所有写入：

atomic。

SQLite：

WAL。

自动备份：

```text
backups/
```

保留：

7 daily
4 weekly

管理员可以：

Backup

Restore

---

# 四十三、不要联网依赖官方服务器

最终目标模式：

```text
Offline Mode
```

在服务器、客户端资源均准备好的情况下：

断开 Internet。

仅保持：

```text
Phone
↕ Wi-Fi
Router
↕
PC
```

仍然可以正常游玩。

如果某些第三方请求不是核心游戏功能：

应阻止或者本地 stub。

---

# 四十四、网络拓扑

MVP：

```text
HarmonyOS / Android
        │
        │ Wi-Fi
        ▼
Home Router
        │
        ▼
Windows PC
        │
        ├ TerraLocal
        │
        ├ SQLite
        │
        └ Admin UI
```

完全不需要：

公网服务器。

---

# 四十五、安全

默认：

```text
bind 0.0.0.0
```

的游戏端口允许 LAN。

Admin：

默认只：

```text
127.0.0.1
```

如果 Admin 开放 LAN：

必须设置密码。

不要实现：

公网默认暴露。

---

# 四十六、版权与项目边界

这是：

个人研究 / 本地兼容服务器。

不要：

- 提供盗版客户端；
- 打包官方 APK；
- 打包官方完整资产；
- 打包受版权保护的完整音乐/剧情/美术资源；
- 使用官方商标冒充官方产品；
- 接入真实支付；
- 绕过付费去获取现实世界收费服务；
- 盗取官方账号；
- 收集第三方账号凭据。

仓库发布：

**code-only**

用户自行提供：

client
GameData
resources

如果某个上游数据仓库的授权状态不明确：

不要把其数据直接 vendor 到仓库。

---

# 四十七、开发阶段

必须分阶段完成。

## Phase 0 — Research

输出：

```text
docs/research.md
docs/protocol.md
docs/compatibility.md
```

分析所有参考项目。

最终确定：

```text
target client
API list
data format
connection strategy
```

此阶段不要大量写代码。

---

## Phase 1 — Vertical Slice

目标：

```text
启动服务器

→ 客户端连接

→ 登录

→ syncData

→ 主界面

→ 干员界面

→ 编队

→ 一个关卡

→ 战斗结算

→ 数据持久化
```

只有这一条链稳定之后才继续。

---

## Phase 2 — Core Game

加入：

```text
inventory
operator progression
mission
mail
gacha
recruit
shop
sanity
stage progression
```

---

## Phase 3 — Base / Social

```text
building
friends
support
daily/weekly
announcements
```

---

## Phase 4 — Events

```text
events
old events
CC
shops
event missions
```

---

## Phase 5 — Advanced Modes

```text
roguelike
sandbox
tower
annihilation
```

---

## Phase 6 — HarmonyOS

在模拟器完整工作后：

测试真实 HarmonyOS 设备。

记录：

```text
docs/harmonyos.md
```

包括：

```text
device
OS version
APK compatibility
network
certificate
proxy
known issues
```

---

# 四十八、Definition of Done

每一个系统的完成标准必须包含：

```text
API implemented
state persisted
restart-safe
tests
no 404 during normal flow
no 500
UI behaves correctly
invalid request handled
admin inspectable
documented
```

仅仅：

```text
页面可以打开
```

不算完成。

---

# 四十九、开发方式

你作为 Codex 不要一次生成“完整私服”然后宣布完成。

每次工作：

1. 阅读当前仓库；
2. 阅读 TODO；
3. 查看 tests；
4. 判断当前阶段；
5. 选择最重要的未完成垂直功能；
6. 实现；
7. 测试；
8. 修复；
9. 更新文档；
10. 提交清晰的变更总结。

如果发现架构问题：

直接重构。

不要为了兼容旧代码持续堆：

```text
if
try/except
magic value
global dict
巨大 JSON
```

---

# 五十、禁止假完成

严禁：

```python
def battle_finish(...):
    return {"result": 0}
```

然后标记 Battle 完成。

也禁止：

```python
@app.api_route("/{path:path}")
def fallback():
    return {}
```

用万能路由制造“没有报错”的假象。

如果功能没实现：

明确：

```text
NOT_IMPLEMENTED
```

并记录。

---

# 五十一、开发记录

维护：

```text
ROADMAP.md
STATUS.md
CHANGELOG.md
```

STATUS：

用表格：

```text
Feature
Protocol
Logic
Persistence
Tests
Client Verified
```

例如：

```text
Login          ✅ ✅ ✅ ✅ ✅
SyncData       ✅ ✅ ✅ ✅ ✅
Gacha          ✅ ✅ ✅ ✅ ✅
Recruit        ✅ ✅ ✅ ✅ ⚠
Building       ✅ ⚠ ⚠ ⚠ ❌
Roguelike      ⚠ ❌ ❌ ❌ ❌
```

---

# 五十二、最重要的测试标准：玩家主观体验

每完成一个 Phase，都要进行：

```text
Player Experience Audit
```

问：

如果我不知道自己在玩私服：

**哪些地方会立刻让我发现这是一个残缺的私服？**

列出所有这些地方。

然后按：

P0
P1
P2

排序修复。

重点关注：

```text
loading
404
500
empty list
wrong currency
wrong notification badge
incorrect timer
buttons doing nothing
inconsistent inventory
lost progress
strange reward
broken event
broken shop
```

最终目标：

玩家可以连续玩几个小时，

而不会不断碰见明显的“私服断点”。

---

# 五十三、最终理想状态

最后，我希望拥有：

```text
TerraLocal.exe
```

双击启动。

看到：

```text
TerraLocal Server
=================

Server          RUNNING
Database        OK
GameData        OK
Client Profile  CN Android x.x.xx

Local API
127.0.0.1:8443

LAN API
192.168.1.100:8443

Admin
127.0.0.1:8080

[Open Admin]
[Backup]
[Settings]
[Stop]
```

手机连接 Wi-Fi。

打开客户端。

进入游戏。

所有主要内容：

```text
主页
干员
仓库
编队
任务
邮件
好友
寻访
招募
商店
基建
主线
活动
肉鸽
```

逐渐达到正常可玩的状态。

游戏进度全部储存在我自己的电脑。

即使 Internet 断开：

依然可以继续。

---

# 五十四、你现在应该做的事情

现在立即开始执行以下工作，而不是仅仅给我建议：

1. 检查当前工作目录和 Git 状态。
2. 如果为空，初始化项目。
3. 阅读本提示词中的公开参考项目。
4. 创建 `docs/research.md`，记录每个项目值得借鉴的架构与问题。
5. 创建 `docs/architecture.md`。
6. 创建 `docs/roadmap.md`。
7. 明确第一个受支持的客户端版本。
8. 建立服务器最小骨架。
9. 建立 SQLite schema。
10. 实现 health endpoint。
11. 建立 GameData loader。
12. 建立 protocol fixture 体系。
13. 开始实现登录 + syncData 垂直链路。
14. 每实现一个真实能力就写测试。
15. 永远以“真实客户端实际工作”为验收标准。

遇到协议字段未知时：

不要凭空编造。

查：

现有开源实现
→ GameData
→ FBS
→ 自有测试客户端的协议记录
→ differential analysis。

如果仍未知：

写入：

```text
docs/unknowns.md
```

并继续完成能够确定的部分。

不要因为某个次要字段未知而停下整个项目。

最终我们要构建的是一个长期可维护、高还原度、版本化、可测试的 Arknights 本地 Server Emulator，而不是一次性的脚本合集。