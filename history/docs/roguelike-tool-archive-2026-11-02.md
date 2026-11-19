# 支援道具的永久图鉴合同

完整目标ACTIVE、未完成。[战斗阶段](roguelike-support-battle-2026-11-01.md)已取得一个新巡逻队地雷落地/数量扣减/触发击杀及真实保存恢复代表；不重购、不重打。

恢复核对HEAD3e76775干净工作区，业务b71f042e/186、schema0036/77。最新实际23用户77表7战斗27报价的保存作为本次兼容基线；221原始输入/186源指纹在.cache/rogue-tool-archive-20261102/protected-before.json。19表e915/v077镜像与CN2.7.71/V070/client_verified=false边界不改。

当前CollectionFacts只投影收藏品及资格；工具购买历史虽已保存并回放current.inventory.trap，没有生成永久outer.collect.activeTool。本轮先核客户端实际消费者，不把有过当前工具直接当全部永久图鉴规则，不填全目录默认获得。

只读metadata确定activeTool为Dictionary<string,ItemUnlockInfo>，Collection有效offset40。具体图鉴位于通用Torappu.UI.ActArchive命名空间；初始只搜Roguelike UI无结果，之后按实际返回类型/图鉴插件定位，未把空搜索解释成无功能。

M195273 ArchiveTrapModel.LoadData 0x4942b0c及M195266 ArchiveTrapListItemView.Render 0x49422e4完整静态解码，工件a91d1e1cc25b0ba239b72a325aabb9aebf0499bad727e926486762827fcb1c81/12288字节/35完整种子；未启动模拟器/服务器/新战斗。REA5888/PID11072/WSL33720实际ready，公开open1成功，pseudo2仍同实际worker待ACK；辅助26385的45秒观察已过期，不重排请求。下一核缺省/锁定/未获得/已获得的读取和完整来源，再实现账户隔离/历史重建/前置拒绝/旧保存兼容。

## 默认图鉴消费者及关闭现场

LoadData M195273 ev_14ba0e1a807c7cf3e64bf891fa5cd24e8779e02da368745e812bf0651d0e0664，50.219秒；默认按archiveComp.trap.trap遍历、主题物品/CheckOpenTime筛选，PlayerData.roguelike.outer[topic].collect.activeTool按工具ID取ItemUnlockInfo.state。缺记录或state0走锁定说明路径；非零状态传入TrapItemModel。保留Type propagation not settling/全局符号警告。

Render M195266 ev_89d547866c8b1334038474637fa94e10b50d53c6f461c10fbdfc249af7936c57，0.078秒；默认state1使用ROGUE_ARCHIVE_TRAP_UNATTAINED和未获得说明，state2显示完整名称/说明及已获标记，其余锁定描述。Hotfix和尾部截断/全局警告保留，不称完整Hotfix/所有UI分支。由此撤回“缺记录可能只等同未获得”的早期未验证假设；缺记录确实会锁定本批工具。未从枚举字段默认值猜2的语义。

5888实际exit0，公开close4成功/server0，Windows11072/33720缺席，221输入186源保持；0新Android/战斗。具体closure/findings/pseudocode仅本地.cache/rogue-tool-archive-20261102/mcp-tool-archive-static-v1。

## 源码与自动检查

新增rogue_tool_archive：仅使用已按完整item/trap/archive指纹接纳且enrollId=None的六项目录及主题开启时间，投影state0/1可用性；取得状态2只来自已完整验证的历次ToolGrant。此可用性/获得投影是本地显式规则，客户端读取语义已核；未抓到官方服务器该状态的写入实现，不冒称自然供给或全部模式资格。读取不回填外层JSON，不添加实体/表、工具余额或新接口，不修改旧报价。实际装备只影响当前探索，永久发现汇总全部保留历史，替换/弃置/结算/新探索不抹除。

CollectionFacts增加独立tools，普通sync的每run验证结果复用；磁盘预检复用容量历史的同一次回放，加入工具来源集合，无需重复每个run回放。首主题投影拒绝伪造state2、未知工具和无依据progress；预检在启动写入前使用已保存时钟校验，无历史不能凭图鉴值授工具。其他主题保持原作用域，已获得历史不因调时到开启前丢失。schema0036/77不变。

新8检查全部通过，覆盖未获得可查看/不装备、购买增量、替换双发现/重复不重置、结算/新run/账号隔离/重启及真实备份、3种坏保存的live与启动写前拒绝、投影失败整事务回滚、开启前后及历史已获不丢。相关7模块154检查通过，阶段162不同检查。4文件Ruff通过，最初两import排序提示自动修正；未发生测试失败，不补造失败/重试。187业务AST通过。既有Starlette httpx弃用警告仍在。证据.cache/rogue-tool-archive-20261102-{new,related}-v1.xml。

真实兼容35153actualexit0：业务2ba37f0a82f234d5ab614c6661b19e5a8d53302140e69d957d95e1401aee14a0/187，仅2旧业务文件+1新模块；独立从已验证quote/index购买行得只有账号23曾获active_tool_2。23完整用户只更新collect.activeTool六行（其他22均6个state1，23地雷state2/其余1），其余所有用户字段精确同旧基线；77原始表/27报价/7战斗完全同。真实备份恢复/重启/新D恢复均23用户77表同，221原输入保持，不回填旧保存。六目录绑定指纹f1df93b1保持。详actual-compatibility-v1/verification.json/users23/all77表摘要。

下一新D同QA23只读原生图鉴代表，使用已有已结算保存/已有同意行，不增加QA工具/购买/战斗；当前尚未准备或启动原生。直接奖励/事件授予、自然价格/权重及全目标仍未完成，无新EXE。

2026-11-06恢复：核实HEAD584fa46干净工作区，现场无自有native/REA进程；上轮只读图鉴副本已于57547actualexit0准备，0夹具请求/0新战斗，23完整用户均同已验新源，6图鉴中仅地雷已获，7旧战斗/27报价保持，226保护输入。之前报告的“尚未准备”是更早阶段，现更正为已准备未启动。继续同QA23只读图鉴原生验收；不复购或重打，新源码2ba37f0a尚待私有检查点，旧业务b71检查点不冒称含本批。

2026-11-06 工具永久图鉴一个只读原生代表通过：017显示TP-II地雷真实图标/每战3个/完整说明，TP-I/III/IV未获得；019补看TP-V/VI及未获得No Info，总6项/已获1未获5正确。0新购买/招募/run/战斗，38HTTP全200/0RLV2/异常及Lua0；同QA23自动登录，无新协议或接受操作。28424/PID33612actualexit0/自有TLS与ADB/index1退出，外层10796也缺席；61其他账号表/226输入保持。完整23用户与准备新源完全同、76游戏原表保持，唯一local_sessions改变；7战斗/27报价保持。原生只读未影响游戏字段，复用此前全23/77真备份重启新D证明，不为记录重复该检查。源2ba37f0a/187、0036/77、162不同自动检查/4Ruff仍是已通过范围，无新EXE。证据.cache/rogue-tool-archive-20261102/native-witness.json及native-readonly-verification-v1。下一私有源码检查点，再支援道具直接奖励/事件来源及自然供给合同；不复购或重打，完整目标未完成。

2026-11-06 本批工具永久图鉴私有检查点完成：源849801ac2af80170d4796a76200b7b079ca3589e/业务2ba37f0a→private609d86fd3dc3fc989e8d7931bf1d5df983a5d602，父96678a4、tree3a5db0accf533699b2a74ccf9d7e923e836ac891。2464729字节/SHA256 1fb47fee0d1dea7359044541b8accfdd8eda3b22e313f89996301282116cefb9/Git blob61ac3be434242821fd35b0ab1b86e85cb2be5116；实际授权浏览器下载双hash/新D555源码文件240完整历史及fsck/干净状态恢复相同。557历史路径2749文本blob扫描无禁止路径或凭据标记；207旧非README项和115788字符完整旧索引保持，新tree210项，private/ref/tree/完整README/note实际回读。新普通Git只读probe128未分类，未称codex/development源码直推。仅本次新C临时下载验证后移D，浏览器未改权限或读凭据；已按新版工具要求完成浏览器completion_summary。准备9836actualexit0、远程核验脚本actualexit0，权威.cache/github-checkpoints/heartbeat-latest.json及rogue-tool-archive-20261106/upload-verification.json；页面截图remote-page.jpg仅本地。包含162自动检查和一个只读原生6图鉴显示/23用户游戏字段保持的实际范围。此完成文字晚于包，不为文字重打包；旧96678a4及全部检查点保持。下一直接奖励/事件工具来源及自然供给合同，完整目标仍ACTIVE未完成。
