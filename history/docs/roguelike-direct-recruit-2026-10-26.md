# 三类部分直升招募券（进行中）

完整交付目标保持，不恢复剿灭、不重复已验FREE/Sharp/晋升或旧关。本阶段只接通明确供给结果的三类直升券，不能冒称自然生成或全主题已完成。

## 固定版本与依据

CN Android2.7.71 / GameData e915675d、19表，具体范围rogue_1/NORMAL/0。all_discount、quad_melee_discount、quad_ranged_discount的实际物品说明均是“部分干员”直接为已进阶状态；原始profession/rarity掩码和展开列表明确，表内没有给出数量、概率或筛选算法。旧静态分类名DIRECT_UPGRADE_RANDOM不代表已还原随机规则。供给方案必须声明direct_pool；普通/FREE/精英/免费晋升券不能夹带这个范围，不把所有候选升级，不捏造官方概率。

REA初次静态两方法被完整解码守卫拒绝：M154637的224字节只解4，M154634的476字节解0；失败目录保留，未放宽守卫。只在index1的原生代码观察副本读取已加载0x3f00000一页4096字节（SHA83ff0c6c1a3835c24e519342ee1f60153de322399af960bb6f6812b5b2d6914f），APK47356684/ELF3ece1e7b/hardware<test-device>核对，未读heap/认证。110保护输入/74表和完整rlv2克隆保持；5HTTP全200/0玩法输入或rlv2/战斗，只有本地session更新。83839实际exit0、服务/自有ADB/index1正常停止，index0保持。

构建8192字节ELF 175e0d5fc507a97151d38828d355b3dcec78e660a713a634ef215428154c3dc7，12完整方法种子。REA默认M154637在插件未覆盖时，按传入展示开关及UI模型+0x48是否正数控制标记；这里只证明客户端显示路径，不把此偏移当未经字段映射确认的服务端公式。M154634遍历插件的覆盖结果，Hotfix分支有bad-instruction截断，重叠全局警告保留。结果ev_7bd8f28b/ev_1308e858，首次49.687秒超过45秒观察期限，原会话后续成功，未重排或重启。公开close及73785实际exit0、31424/37220现场缺席；代码页保持。

## 实现

schema0033增加direct_pool，保存供给报价/票券/探索回放的范围绑定。DIRECT为内部独立候选类别，必须有正数永久干员来源，线缆仍投影NORMAL/upgradePhase1/isUpgradefalse；E2上限按既有两级表及永久练度快照形成，不替低练度账号补造精二养成。首次按该稀有度基础招募费扣希望，临时与原普通晋升费用保持；永久阵容不变、重复序列不重复招募、已直升者不再提供普通/免费进阶。范围必须匹配当前未用且实际拥有的四星以上可获得角色；失配时购买/源石锭/库存/票券一起回滚。普通候选及备用角色继续保留，未标记者不自动直升。持久化恢复不依赖永久干员后续训练，历史编队以原候选为基线。

旧报价三字段与摘要不变，elite_pool旧报价也不变；只有明确direct_pool加入新报价摘要。0032旧列/精英范围保持，只给票券追加[]；迁移约束重建在同一事务，可故障回滚；最新版本章与旧模式表结构不匹配时在只读预检拒绝。

## 实际检查与失败

最终191不同检查，26新/165相关，逐用例最后结果均通过；没有全仓库/全模式零bug声明。14修改源码与测试文件针对Ruff通过。初批direct-v1有14通过/6失败，均为新测试误用formation参数，业务购买/招募已到达该断言；按真实formation(run,troop,slots)修正。v2有10通过/2失败，是新迁移测试漏导入create_game_app，补入后两项重验通过。related-v1有160通过/2失败，旧特殊券拒绝消息和0019只追加一列的期望已落后；改为要求明确范围、逐旧行保留并追加两个空列后仅重验这两项，不重复通过批次。

针对检查含三券/精零与精二、部分候选保持普通、技能专精和费用、增量/同序列、缺范围/错误职业/稀有度/未知与备用引用拒绝、未拥有供给原子回滚、永久练度后改不改探索快照、主动放弃、招募flush后故障回滚、并发只一份结果、篡改范围/报价/类别/来源/模板只读重启拒绝、0032精英范围/旧行迁移与故障回滚、最新章旧结构拒绝。

首次冻结核验脚本漏导入create_game_app，在第一HTTP之前失败；原脚本和direct-frozen-qa失败副本保留，未覆盖或重跑原生。在新D direct-frozen-qa-v2完成：三券各一明确QA结果（清道夫/桃金娘/杰西卡），63HTTP全200、E2等级15/实际技能与专精/基础2希望、只扣所选费用、再进阶排除、永久训练保持。旧账号1–8完整rlv2相等，全部74表旧列不变；Runtime重开、备份恢复及新D direct-frozen-new-d-restore-v2全部user/74表相等，109输入保持。0新玩法原生/实际战斗/EXE；代码读取会话不算玩法通过。

本地证据`.cache/rogue-direct-20261026/`：source-inventory、matching-descriptions、rea-direct-static失败、rea-direct-loaded-v1、mcp-direct、direct-*.xml、direct-validation、direct-frozen-verification；`.cache/rogue-direct-code-20261026-v1/`记录代码读取与正常收尾。官方表/原始代码页/反编译/存档只本地。下一步保存私有源码检查点后做一次新直升原生代表，随后推进费用修正及正式供给。自然直升数量/概率/资格、费用修正、正式节点生成、完整主题/其他系统/成熟EXE仍未完成。


2026-10-26直升源码检查点9e6fa22168918fb91cf5f3899a1e681e6ed71e4c私有回读恢复完成：上传/索引c22211521cd3e0d96b7f98ff3591864617978e84，完整bundle1649364字节/SHA256 a95a26f957e031b3c634404d56490ab6774fc71b23e72b3fd348832d94441b6c，426自有文件/131历史提交、428历史路径/1622blob扫描无禁止路径及凭据标记。保存166旧非README条目及旧索引全文。已授权连接器完整bundle备用方式，未声称源码分支正常push、未强推或公开仓库。API回读head/tree/索引相等，固定提交网页View raw实际下载双SHA一致，新D restored-remote-9e6fa22全部源Gitblob/完整历史/Prompt/fsck/干净工作区相等；只把本次短暂C下载校验后移D，旧包/保存/发行物保持。网页实际9e6标题/源码/业务哈希/schema33/完整SHA截图已保存checkpoint-proof.png；本次截图成功，旧11cb截图失败记录保持。包内含8a74c808、三类明确直升结果/191不同检查（26新165相关）/冻结63HTTP/旧1–8和109输入/74表全恢复，以及晚于610包的Sharp单次原生记录。未验直升原生/自然资格和概率、费用修正/正式供给/全交付仍未完成。权威.cache/github-checkpoints/rogue-direct-supply-20261026/upload-verification.json及heartbeat-latest；本条完成文字晚于源包，不为记录再次打包。下一步仅一个新直升原生代表，不重抽旧类型、不重打旧关。


2026-10-26直升原生v1及归属缺口修复：新D账号12/后方协调资深券明确杰西卡结果（非官方自然概率）；15HTTP准备保留旧74表行/112输入。screen13候选进阶图标/招募2希望、14精二15/双技能专精、15原生招募动画、16实际可用希望3→1/售罄/2人、17-18入队技能和图标保持。36HTTP全200，仅一次recruitChar(3,2)，无战斗/旧关/旧类型招募重放；永久阵容不变/训练历史0、property仅希望cost6→8(max9)。11862实际exit0/实际32692缺席，服务/自有ADB/index1正常停止，index0保持；Runtime完整rlv2/备份及新D全74表相等，所有其他账号/全局行相等。errors0036无Exception/JSONPath/Lua nil；音频未验证。screen01直接标题，START后screen02黑过渡、screen03自行进入登录页，整个会话0 Back输入，原先“普遍必须Back”判断撤回；旧失败保留，不称已修复或认定根因。screen05实际本地service说明核对后仅记录本地版本确认，公告screen09显示/关闭；没有官方认证。

随后源码审计发现9e6fa22的真实DIRECT来源归属缺口：validate_sources及active的source_ids集合漏DIRECT，正数外账号/未知/错误角色来源可能漏检。执行精确旧提交validate_sources AST确认外账号DIRECT未拒绝；新代码两处纳入DIRECT，保留旧提交/失败依据，不以此前191检查冒称安全已完整。3新反例分别验证现场请求503/事务无写入及只读Runtime预检拒绝，连同六个三券/低练度正向分支，9项当前检查实际exit0。当前业务56fbdb52ea135c36bd0d7f2b38465327e706320fdb35f6864e7673477563092a，只改rogue_runs.py归属守卫，schema33保持。新D owner-fix-new-d-reopen-v2对真实原生存档完整rlv2和74表相等，113保护输入保持，0新原生/战斗。第一新D复制因settings.save已创建profiles而copytree缺dirs_exist_ok失败，失败目录在数据库复制前保留，修正复制工具后新v2核对，未覆盖源保存或重跑原生。旧191检查保留为8a74基线，新增3归属用例，194不同累计范围不能当成194项全部重跑。

记录脚本首次因单引号跨行导致SyntaxError，尚未写账本；后续同shell未停止，16409dd只提交了两处源码/测试文件，提交标题提及原生但正文记录实际在下一文档提交补入。保留真实Git顺序，不重写历史或称旧提交已经含报告。下一步保存修复私有检查点，再推进实际希望费用修正/正式供给；自然直升资格/数量/概率及完整交付仍未完成。证据.cache/rogue-direct-native-20261026-v1/{verified-native-direct.json,summary-0035.json,errors-0036.json,requests.jsonl,native-results.json,screen13-18,direct-native-new-d-reopen,owner-fix-new-d-reopen-v2}及.cache/rogue-direct-20261026/{ownership-counterexample.json,ownership-validation.json,ownership-frozen-reopen.json,direct-ownership-v1.xml}。本轮原生与修复记录晚于9e6私有包，不能冒称已在该包内。


2026-10-26归属修复检查点5b03965完成私有实际回读/新D恢复：上传及索引0f795cd60e06929c7406f762336b7b31e4bacd0f，完整bundle1659787字节/SHA256 b8553925554ae6ccff0747494ccaa2d961c7cf0928c69fc8f0724d4c48679fe8。426自有文件/134历史提交、428历史路径/1639blob扫描无禁止路径/凭据标记；保留167旧非README条目及旧索引全文。已授权连接器完整bundle备用方式，不称正常源码分支push；固定提交网页View raw实际下载双SHA匹配，新D restored-remote-5b03965全部源Gitblob/完整历史/Prompt/fsck/干净工作区相等。只把本次短暂C下载再次核对后移D；旧包、保存及发行物保持。API head/tree/索引回读相等，网页最新5b标题/源码/56fb业务/schema33/完整SHA截图成功。包内包含DIRECT归属两处修复/3新反例（9当前检查、191旧基线、194累计非全重跑）、精确旧提交反例、杰西卡一次直升原生36HTTP/2希望/卡片动画/保存恢复/0战斗，以及0 Back启动反例修订。自然概率/资格、费用修正、正式供给、完整玩法/EXE仍未完成。权威.cache/github-checkpoints/rogue-direct-owner-20261026/upload-verification.json及heartbeat-latest；完成文字晚于5b源码包，后续随实质检查点保存，不重复生成纯记录包。
