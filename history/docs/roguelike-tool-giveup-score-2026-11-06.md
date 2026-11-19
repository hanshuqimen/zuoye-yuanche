# 主动放弃的工具计分来源与版本

完整交付目标仍未完成；本轮只补当前首主题NORMAL0主动放弃的工具取得来源，复用已完成工具购买/战斗及原生评分证据，不重打旧关或恢复剿灭。起点f34f121干净、业务9cfbecdf/187 Python、schema0036/77表；上一源码bab2ada已在私有3ddb578实际回读和新D恢复。

## 已核问题与依据

rogue_giveup.compile_facts仍用len(relics)-1且旧注释宣称工具没有来源账本；当前ToolHistory已经从验证商店报价/付款和节点因果顺序保留ToolGrant。自然结束collected_relics已计非招募券购买，主动放弃没有把实际工具取得加入counts[5]，因而少算该类物品。

复用已有REA工具身份/本局来源/结果消费者证据，不声称反编译到了官方服务器评分公式。[PRTS主题页](https://prts.wiki/w/傀影与猩红孤钻)本轮检索的常规NORMAL0规则为每获得物品5分（包含工具、排除金币与招募券）；这是已有明确的玩家规则适配来源。最新实际存档两个工具原生代表counts分别[0,2,0,0,0,1,1]→9分和[1,2,0,0,0,1,1]→39分，与保存响应/已看原生结果一致。该证据不推广其他主题、难度、活动或自然供给权重。

## 实施边界

拟用独立的工具give-up事实v2及closure v2，只用于今后真实持有工具来源的新放弃记录；无工具保持v1，旧v1关闭/结算按原版本回放，不追奖或重算。工作流run v3、既有外层评分/通知策略和schema不变；新能力版本位于有界关闭事实，旧reader应拒绝该版本而非静默漏算。

工具计数来自完整验证的本局ToolGrant，保留visit/stock/item/at身份与顺序，重试不能增加取得次数、装备替换不抹除过去来源。图鉴与结果显示的按ID去重策略独立，不以跨局永久发现记录计分。具体检查与真实存档兼容结果后续追加；原生新放弃工具分数仍未验。

## 源码与实际验证

仅改rogue_giveup.py：新增事实rogue1-normal0-giveup-tool-facts-v2、关闭意图rogue1-normal0-explicit-giveup-tools-v2。有工具的新关闭才选择v2；无工具及已存在v1均按原版本计算。完整运行回放只做一次，取得有序ToolGrant后逐条核对本局已付款shop/stock/item/at，保存完整来源数组并纳入事实hash和closure规则hash；同来源重试不重复计数，不同来源再次获得同ID仍是独立取得。旧v1即使有工具也不升级、不加分；新v2若来源/数量/版本不符，线上及启动前拒绝，不默认为旧版。新能力以closure版本明确区分，旧reader不接纳该新版本；外层评分/通知v11、run v3与schema0036/77表不改。

新15检查actualexit0，包括单次/替换/同ID新来源、旧槽重试、增量、一次确认、已确认/未确认旧v1不追奖、真实备份/重启、两runtime并发只发一次、intent插入故障回滚，以及重算hash后伪计数、缺源、错物品、错槽、倒序、重复源、未知版本、降版都拒绝。相关6模块114检查actualexit0，合计129不同检查；2文件Ruff/187业务AST/diff通过。初次1个import排序由Ruff修正，检查没有测试失败；保留Starlette httpx弃用和相关Pydantic alias上下文警告，不把警告当新功能完成。

业务85a020afb07be19c3cc9090634c79ad741b512bd46f41a9de7d74c67d91842f2、187 Python。actual-compatibility-v1完整23当前用户/77原表/7旧战斗27旧报价保持，原v1关闭事实和hash保持；真BackupService备份恢复/重启/新D同，232输入字节保持，89419actualexit0。原生工具放弃画面、真实新v2通知完整消费尚待一个代表；以上不是全模式或官方服务器代码恢复。

准备一个新的D盘QA23副本作为新结果合同代表：沿现有API初始化并关闭三张招募券、显式单SHOP/地雷价1、购买一次后主动放弃，保留真实未确认的v2结束意图；不会修改SETTLED或伪造pending。地图、库存及价格明确QA，不称官方自然供给。原生阶段仅看该结果并确认一次，0新战斗，不重复测试已通过购买方法。生成器.cache/rogue-tool-giveup-20261106/prepare_native.py已写、尚未执行；源提交后再准备及启动。若出现新的协议页按当次操作规则处理，旧确认不补造新接受。


## 2026-11-07恢复原生现场

2026-11-07恢复工具放弃原生验收：旧58404句柄缺失，Windows实际无该Python/dnplayer，18443无监听、index1已停；v1只有5个配置GET200，native-results不存在，不补造退出码/收尾。完整23用户与准备值同；首次要求77原表同的恢复守卫失败，查证仅local_sessions变、其余76游戏表同，失败诊断保留且未创建副本。按实物修正边界后，新D/v3仅复制同一真实未确认v2意图，不补造pending、不再初始化/付款；新0 API/战斗，240输入保持，25052actualexit0。源f908aa0/85a/187不变，129检查不重跑。新副本.cache/rogue-tool-giveup-native-20261107-v3及refresh-diagnostic同名目录已准备未启动；下一只看结果并确认一次。原生工具画面/计分仍待验，完整目标未完成。 旧v1尚未执行任何tap/drag/协议接受；004截图仅登录加载START，不能当原生结果已验。新脚本复核旧76游戏表/23完整用户、真实ABANDONED和closure v2及无确认账本后再复制，重新绑定仅本地SDK接入；不把local_sessions差异冒称游戏保存被改或77原表保持。

## 新工具放弃计分原生代表通过相应范围

7f40415文档恢复点/业务85a020af/187启动新v3，当前同QA23ResourceRelic23手动START与本地账号登录后进入主页，无新协议页或接受动作。终端待办→继续探索→真实未确认结果页；原生阶段没有新创建、购买、招募或作战请求，唯一RLV2为gameSettle一次200。原始13次API夹具准备属于此前v1，不把它们算成官方自然供给或原生购买通过。

实际已看022-score-stable：获得物品数1/对应5分、通过步数1/1分、其余0，总分6、蜡烛+6；024-notes显示笔记70/200、灵感+1；026-returned回到开始探索且幕后筹备7。与准备值64/6→70/7一致。确认只写一次v11结算，run为SETTLED，保留原v2关闭事实；计分与显示分别验，不推广所有模式。准备使用地雷价1和单SHOP的显式QA，不标为正式价格/地图权重。

43HTTP全部200，异常类型和Lua nil0，0新原生战斗。输入均ACK后等待3.6秒再捕获/实际看图，文件时间交叉核得最小间隔5.080856秒。59463实际exit0，30636已非运行中的自有Python，18443无监听；自有服务、ADB子进程和index1退出，61其他账号表及240保护输入保持。没有停止index0或别的模拟器会话。

native-save-compatibility-v1/verification.json与native-witness-v3.json：真实确认前备份确为ABANDONED、无确认账本；之后只有本局变SETTLED、添加一份6分结算。所有旧探索/旧结算行保持，关闭意图行全部字节同；外部状态只有bp64→70与pointOwned6→7，其他字段同。旧22完整用户保持；7旧战斗、27旧报价及1份本批QA准备报价保持。最终23完整用户/77表在真BackupService备份恢复、重启、新D恢复全部一致，94806actualexit0，原副本不覆盖。129既过自动检查未重跑，新EXE仍无。

## 结果页工具图标预期纠正与过滤消费者

015/016/019前页实际显示0干员、0收藏品且没有地雷图标，服务端summary-0018却明确含activeToolList=[地雷]和inventory.trap；客户端异常及Lua0。**撤回“只要activeToolList非空，前页就必须增加图标/数量”的无条件预期**；计分页的获得物品1与前页收藏品分组0不是同一个计数。先保留反例，不改原生过滤或以HTTP200称图标通过。确认前另存真实pending-before-confirm-v3.sqlite3（SHA256 74442144c49da5c5127dc4d3fd97b1adf34a7539b0211bf9ff1b2ba4bf71c206），今后复现可从新D复制，不手改已确认的SETTLED或重打关卡。

新REA工件728d2e328db3e28cb5800568993176f42195ba6c07908e6ff70985ae5902ad24，8192字节/14完整种子。M151846 get_showTrap104/104，ev_c524ea7d5b74c6425fe600f6ecc531dc819cb2b754499d732c3df55441c96c9b，默认读取this+0x3c，Hotfix坏指令与全局重叠警告保留；不拿编码元数据偏移当作实际对象偏移。M151848 Render356/356，ev_d497b9677817c608b6f84391371ca909a21ed1dbb0c0f18285e92dfbdb296eb0，完整默认路径调用get_showTrap，传(~showTrap &1)<<8给M151932，再用返回列表数量写前页计数；只有全局重叠警告。复用已核M151932的bit8排除trap分支。因此即便工具模型存在，仍可能被原生分组过滤；不能从列表非空推出必须显示。

这尚未直接读取实际prefab/Hotfix的showTrap值，也没完整核本页TrapViewModel实例，所以**具体“图标未显示”的原因仍未完全归因，图标显示不标通过**。本批没有为了符合预期强制改客户端/模板；此前服务端字段投影保留为有依据的工具模型输入，成员去重仍为明确本地策略，不称官方后端成员规则已恢复。

REA41546公开close4成功/server0/actualexit0；首次观察45秒pending后同worker于76.984秒返回，未重排，后续0.031秒。旧Python17472关闭后该数字被系统复用为smartscreen，24124缺席，不把旧数字当活REA或停止无关进程。原始伪代码/页面/SQLite/日志/图片仅本地.cache/rogue-ending-tool-visibility-20261107与native目录，不进Git。

下一先保存本批85a源码和实际新计分证据的私有检查点，再核具体prefab显示过滤/工具工厂；不重复已过的计分、购买或关卡。直接奖励/事件自然供给、其他玩法、Golden/断网长时/性能/Harmony/成熟EXE及完整目标仍未完成。旧private3ddb578仅含上一9cf源，不能冒称已备份85a。

## 2026-11-07本批私有检查点完成

恢复核对06a0e79干净、业务85a/187与上次9cf有新增源码，本轮不重复已过检查或原生游玩。首次手填完整提交号错误被HEAD预检拦截，尚未生成包/上传；保留prepare-guard-failure.json，改为直接git rev-parse HEAD取得真实06a0e79cd896f71f35e54e615bc1850be50eb2d8，不以猜测补全短ID。后续准备72437actualexit0，560当前文件/246完整提交/562历史路径2802UTF8 blob扫描，无禁止收录路径或凭据标记，新本地D恢复一致。

源06a0e79cd896f71f35e54e615bc1850be50eb2d8/业务85a020af→private456e1c2d4e91927bb9858b55ec12fab830ce006c，父3ddb5781930c3e4b2bfd37e7a800ecf7651c257a、tree346b505daf1dc8f8a6ee58f45d4727bc7a71b7ed、README29bb36e60a6fc0edb170d66b31dca215307656bc、note9c7f62dc4f9d3e00820df5e2361f40cae6a8d5bf。bundle2506860字节，SHA256 6e87c0d4bd4999d6bc7fc9277d36a3be26444c3d6026440a425268e38d64e445、Git blob9cc2331a6f0c4d87bb47cae25406e80466991192。

普通Git专属只读探测关闭交互提示并限时，1.547秒实际128，无输出ref，错误只提取prompt-disabled/network标记、不打印原始内容；没有成功源码传输证据，不称codex/development直推。连接器逐对象SHA一致，expected_sha/force=false提交；private/ref/commit/tree/完整README/note实际回读，新tree214项，211旧非README项及116915字符完整旧索引含原CRLF保持。没有改成公开或扩权。

已授权IAB实际文件页语义下载控件返回本次真实下载路径，随后立即完成浏览器completion_summary。保存并在对话嵌入remote-page.png作为文件页证明，原生图片没有入Git。远程核验脚本actualexit0：实际下载SHA256和Git blob双hash一致，新D560文件/246完整历史/完整tree与source blobs/Prompt/fsck/干净状态恢复同。只将这一个新C临时下载在双hash后移D，不动旧下载/备份。

权威.cache/github-checkpoints/heartbeat-latest.json、rogue-tool-giveup-20261107/upload-verification.json及restored-remote-06a0e79。包内明确129自动检查、工具原生6分与23用户77表恢复相应范围，也保留前页无图标的反例和实际prefab/工厂未完成边界；不把原生计分通过改写成图标/全玩法通过。旧3ddb578及全部检查点保持。完成记录晚于包，不为文字另打包；本轮无新原生游戏操作、源码业务改动或EXE，完整目标仍ACTIVE未完成，下一继续具体显示过滤/工具工厂。


2026-11-07后续冻结资源核查已读出具体默认值：9月独立ui/rglktopic/rogue_1.ab的结束页→统计页→收藏品组件本地引用链明确，内嵌_showTrap为UInt8/0；清单ZIP成员大小/MD5及SHA通过。结合原REA默认过滤，说明该prefab默认不把工具计入前页收藏品分组，和原生反例一致；不再将此配置记为未知，也不强改显示。当前运行Hotfix/所有主题仍未验证。工具计分通过范围不扩大；0新原生/战斗，详[资源核查及失败记录](roguelike-ending-prefab-inspection-2026-11-07.md)。
