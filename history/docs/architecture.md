# 架构

## 权威状态与事务

SQLite 中的账号、玩家、资源、干员、编队、战斗、任务、邮件、招募、寻访、基建、商店、活动
分别持久化。syncData 是这些实体的客户端投影，不能反过来作为整个玩家存档。

协议适配器解析请求 → 领域命令 → 单个数据库事务 → 事件处理 → 状态 delta → 提交后返回。
SQLite 使用 WAL、外键、busy timeout；每个账号的写命令串行进入事务，并用唯一约束和操作收据
防止重复领取、重复结算和资源透支。进程中止只能留下提交前或提交后的状态。

GameData 经过 importer 验证、规范化、内容 hash 与 schema 指纹后形成只读版本缓存。
领域逻辑使用 GameDataAdapter；协议使用独立 ClientCompatibilityProfile。
所有业务时间通过 ServerClock，真实测时和审计时间与虚拟游戏时间分别记录。

## 模块

- server/api：显式路由；版本协议层与本地管理 API 分离。
- server/domain：养成、资源、战斗、寻访等独立服务。
- server/persistence：实体、事务、迁移、备份和幂等收据。
- server/protocol：syncData、delta、错误与战斗记录适配。
- server/gamedata：验证与版本缓存。
- admin：本地 Web UI；所有写入调用相同领域服务并留下 audit_log。
- launcher：Windows 进程生命周期、TLS、地址展示、诊断和停止。
- client_helper / tools：自有实例、按版本适配、脱敏 fixtures 与对比工具。

## 部署

单进程 Uvicorn 提供游戏服务；独立管理监听只绑定回环地址。
默认游戏 HTTPS 8443，管理 HTTP 8080。默认不启动录包工具、不转发官服、不自动升级资源。
配置、数据库、证书、缓存、日志与备份保存在可写 data 目录，不使用 exe 解压临时目录作为存档。

管理面板采用离线可用的 HTML/CSS/JavaScript：深蓝色导航、白色工作区、蓝色动作、清晰表格，
系统中文字体，无外部 CDN；功能验证状态与服务运行状态分开展示，空状态给出具体下一步。

