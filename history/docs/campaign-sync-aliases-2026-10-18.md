# 剿灭入口空白：同步别名修复

独立19表配置能够登录，但原版“常态事务”页没有剿灭卡片。服务器投影的上限为1200且轮换开放；客户端对应剿灭对象仍是上限0、activeGroupId/rotate/rotateGroup均为null。不能把此前的字段声明审计和服务器测试当作原生同步验收。

## 根因和修正

冻结metadata的精确字段token及JsonProperty属性证明，下列CLR字段名与JSON键不同：

| CLR字段 | 实际JSON键 | 字段ID / token | 属性范围序号 |
| --- | --- | --- | --- |
| PlayerDataModel.campaign | campaignsV2 | 17824 / 0x040045a1 | 8548 |
| StageOpenInfo.rotateGroup | rGroup | 15485 / 0x04003c7e | 8407 |
| StageOpenInfo.trainingGroup | tGroup | 15486 / 0x04003c7f | 8408 |
| StageOpenInfo.trainingAllOpenGroup | tAllOpen | 15487 / 0x04003c80 | 8409 |

根字段使用JsonProperty(string)构造参数，后三项使用无参构造及经setter映射核对的PropertyName属性。先前报告中的`campaign/open.rotateGroup/trainingGroup/trainingAllOpenGroup`是内部声明名，**不是已验证的线上JSON键**。本记录修正这项推断。

完整同步根改为`campaignsV2`，开放组通过Pydantic显式别名输出。领域构造和周上限计算仍使用内部属性名；快照使用by_alias，增量差异因此沿用相同JSON路径。没有同时发送两套字段，没有改数据库、版本绑定、理智或发奖规则；演习、剿灭结算和周刷新不会因别名修正而自动实现。

## 原生与资源证据

独立v4使用同一冻结SDK v3 APK及实际TLS，本次正常停止服务、连接工作线程和实例1。58表仅local_sessions变化；52张其他账号关联表、307项保护输入及1079份旧发行文件保持，数据库/外键通过，活动战斗0。旧实例及旧验收库没有切换配置。

对常态事务面板取得两个文件映射页8192字节，SHA-256为`b62f7b5b7e83b12df4ce399b147b88e7ae1132f4ce2d9483cc0b5ef9de105e61`；泛型singleton补页4096字节为`38752c57204bff7deeb5c89645e87db4deab8fd13e375ff57c5e8d3e3c1cfa26`。通过冻结声明、getter及类型核对，仅只读检查该独立QA的剿灭字段；没有扫描内存、修改内存或读取认证字段。首次映射筛选及嵌套类型名称断言失败的检查不计为成功证据，修正后记录36次有界读取及实际默认值。所有Android指令保留8秒限制。

还从原APK的94个匿名bundle中列出静态TextAsset，剿灭表资产99064字节，SHA-256为`ab05a1f02c94b4b919422c11b3d8528bfde337b28378d5c16e1a8a52d3875b18`。按冻结字段声明解析FBS，7个配置分支逐值相等：21永久组、36区域、15分区、6常量、33轮换、75训练及11全开放窗口。另核对1-5、2-8、camp_01及camp_r_33的五个关卡标识/路径字段。这里只证明这些投影，不声称完整FBS或全部GameData已经逐值还原。

本地原始证据留在`.cache/rea-2026-10-18/campaign-entry/`，原生截图和正常停止记录在`.cache/campaign-native-20261018-v4/`，不进入Git或服务器发行物。REA native provider原有不可用状态未通过重装绕过；本轮沿用冻结调查资料、已核对索引和有界本地/加载代码分析。

## 验证状态

修正后首轮专项68项通过（20.15秒，一项既有httpx警告）。补充完整同步和3807增量对真实短别名的断言后，完整1076项通过（175.67秒，一项既有httpx警告），Ruff零诊断。

独立v5复制v4的58表，没有新增通关/奖励夹具。真实客户端冷启动后，54次有界只读检查证实上限1200、activeGroupId=camp_g_21、rotate=camp_r_33及rotateGroup=group_r_33。原版终端0/1200、常态事务卡片、世界地图、拉特兰分区、“默祷圣祠”详情及战前编队均已观察并保存截图；训练名单和突破阶段显示正常。这里验证的是对应页面，不包括所有分区、全开放训练或战斗动画。

在原生引导中实际加入已持有的芙蓉后，点击开始产生`POST /campaignV2/battleStart`，确认此前的静态候选路径。脱敏结构为usePracticeTicket:int、stageId:string、squad:{squadId:string,name:string,slots:[{charInstId:int,skillIndex:int,currentEquip:null}]}、assistFriend:null、isReplay:int、startTs:int。专用接口尚未实现，因此返回501并显示原版断线提示，不能声称已进入剿灭战斗；没有新增BattleSession或理智变化。不得用普通战斗结算或万能成功响应掩盖该缺口。

v5的57条请求仅该专用开战一项501；登录、完整同步和3807刷新均200。正常停止后58表仅本账号的登录、引导和编队相关六表变化，其他账号52张关联表、359项保护输入和1079份旧发行文件保持，数据库/外键通过，活动战斗0。证据为`.cache/campaign-native-20261018-v5/entry-audit.json`和对应截图；业务源码摘要为`13acb11892b7fb4c44383aa420d0fa60d9c7c0f733633093401dc038fa9d643d`。

v3的更晚持久化记录显示0-1与tr_01各一次开战/结算成功，56条请求无错误；没有其完整视觉证据，不能扩大为剿灭或引导全流程验收。v3缺少正常停止结果，保留只读关闭审计。

剿灭实际开始HTTP已取得，独立战斗/结算、结束HTTP、击杀语义、精确周收益、突破/委托领取及刷新/扫荡仍待完成。集成战略、卫戍协议、危机合约、剩余寻访及全游戏原生视觉、Golden、完整离线、两小时、性能与HarmonyOS继续保留；本阶段没有新EXE或成熟交付声明。
