# 普通剧目的单次战斗经验加倍

接通《一百零一日》在同层下一次战斗获得指挥经验+100%的效果。当前支持三项普通剧目：《初晓》《金羽兽》《一百零一日》；其他23项、官方自然供给与概率仍未完成。前两项的领取、当前栏、节点预告、消耗及完整保存恢复已通过一个原生代表，见[原生记录](roguelike-capsule-flow-2026-11-11.md)末节；本批经验加倍只做接口和保存验证，没有新增Android输入或原生战斗。

依据是实际导入e915的19表、v077/77.6.0/client_verified=false，具体rogue_1/NORMAL0、创建时间1792645099、主题已开放并归档。冻结客户端CN2.7.71/V070，不称全部同版。剧目3物品完整指纹2d2442ca…28aa360，capsuleDict完整指纹0dafbba7…765b60d，类别BATTLES。效果来自该版本的明确物品定义；单个buff.capsule和领取协议沿用既有REA证据，经验投影沿用M33775及等级栏/结果栏消费研究。本批没有新REA会话，不把元数据查询当作新逆向成果。

源码继续用已校验奖励收据重建单个当前剧目。BATTLES对应普通、紧急和首领类别，必须同层可达；不会把地图里不存在的BATTLES字符串当作节点类型。开战时激活，结算或放弃该战斗时消耗，之后的战斗不再加倍。胜利按匹配关卡的基础经验乘2，再计算累计经验、级内经验和逐级收益；战败不获得经验。普通/紧急、中间首领和默认最终首领沿用各自原有结算边界。经验变更、剧目消费和收据在同一事务；重复请求、并发请求和重新启动不会重复发放。未接通的等级生命/部署上限收益在开战前拒绝，避免开战后才无法结算。

同时修复一个开战前检查缺口：旧未规划奖励的接口仍要求唯一GOLD物品，但此前允许存在多种GOLD时开战，随后结算报ROGUE_GOLD_ITEM。新反例先实测返回200，失败XML保留；现在开战前复用原有货币校验，不创建战斗、收据或消耗剧目。显式奖励方案仍用gameConst.goldItemId。旧STARTED的重试和历史计算路径保留，旧规则摘要不改；这是防止进入已知无法结算的分支，不把缺少奖励方案的旧入口冒称正常可玩。

最终185项不同相关检查通过，13项为本批新增，合并证据为experience-final-audit-v1/final-checks.json。覆盖普通/紧急的完美、损伤通关和战败，单次加倍、后续普通经验、同序号及新序号重试、双Runtime并发、写入后的回滚、开战等级限制、伪造经验冷启拒绝，以及中间和默认终局首领。旧回归的一项招募测试随机进入付费晋升，但夹具缺完整进阶券；只给该测试补自有完整夹具及物品引用，未放宽生产规则。首次夹具修补漏物品引用导致导入错误，随后修正。新测试最初四失败来自未给多货币夹具配置完整奖励方案，随后只改明确QA方案；另一次回滚注入compute影响了更早的因果回放，改在已写入后的response注入失败。所有失败XML保留。

真实数据从QA34最终34用户保存复制到新D目录。当前源码读出的完整34用户及78原始表与既有原生审计相同，两旧剧目规则摘要保持。只新增QA35，两场战斗均为合成API遥测：ro1_n_1_1基础10/获得10，领取剧目后ro1_n_1_2基础10/获得20，总经验30，LV2级内20。一次领取、一次消费，重复结算不重复增加；原34用户、11旧战斗和全部旧行保持。新35用户、共13肉鸽战斗，普通battle_sessions仍0。

actual-experience-v1在第一场已结束后调用不存在的等级position方法而失败，未重放这场战斗。v2新D复制失败保存，合法本地QA35重新登录后继续领奖及第二场；6个续接HTTP均200，原部分HTTP总数未取回，不按收据补造。actual-experience-v2/36690实际exit0，完整35用户/78表真备份、恢复、Runtime重启及restored-new-d一致。末版仅再抽出相同货币校验并加入开战防护，experience-final-audit-v1实际exit0冷读working与restored-new-d的全部35用户/78表仍一致，未为记录重复备份或游戏请求。

末版业务e287f034c4d7117564697aa30e099e0af8b2e3c33fe6ef03bf253f8f1a1a08ff，200Python、schema0037/78表，无迁移；六业务文件及两测试文件变更。源原生DB/settings、失败副本、前置种子、旧检查点索引和所有其余保护输入摘要保持。Ruff、AST和diff检查按实际结果登记。本地证据`.cache/rogue-capsule-acquire-20261111`内exp各版XML、actual-experience-v1/v2、experience-final-audit-v1及保留的经验结果页种子；官方数据、保存和工件仅本地，不进Git。

经验加倍的原生战斗动画、其他剧目、自然池/权重、其他全部命名模式、成熟发行及完整Golden/断网长时/性能/Harmony验收仍未完成。下一先保存本批私有源码检查点并核回读/新D恢复，再继续普通剧目及节点规则；不重复《金羽兽》原生代表或已玩关卡。

2026-11-11 普通经验剧目私有检查点实际完成：源码1d8f25752b188526f05afb80748f1d61d23cc311、业务e287f034、200Python/0037-78 → private3baf9613295d377872efbbb8872f86301368c43d，父9bd2baf/treef9700fbe53adeb653ba49e734ea95adf0ce0a62f。旧246条目与README blob保持，只有新完整历史包和清单两项。包2842084字节，SHA256 c6e95e96c218e15c319b2a32079c1bcc2f4117c8fa3597ba97d5ce897e803525，Gitblob cc8a3c805a3c407cd71834fa5c69aa2922835556。621源码文件/299提交、新D完整tree/blob/Prompt/fsck/clean恢复同；623历史路径3357 UTF8 blob扫描无禁入路径/凭据标记命中。

普通Git非交互probe1未登录、无ref；连接器可实际读写私有仓库，Git data追加对象并expected_sha/force=false更新main，非codex/development源码分支直推。连接器二进制回读依次UTF8解码错误/base64大文件空/通用fetch拒非UTF8，未绕过任何认证或安全阻止，改用已授权网页精确提交View raw。实际Download事件入站，双hash后只将本次新C临时文件移D；新D完整恢复actualexit0。旧备份/README/索引原字节保留，heartbeat-latest及local-latest权威索引同步。没有访问本地8080、扩大权限或读取浏览器凭据；本次网页只读下载，无新网页上传或法律确认。

本地证据.cache/github-checkpoints/capsule-exp-20261111/{prepared.json,git-transport.json,old-remote.json,readback-tree.json,manifest-readback.json,remote-meta.json,upload-verification.json,received-web,restored-remote-1d8f257}。包含185不同相关检查、真实35用户78表恢复、旧34用户11战斗保持、QA34金羽兽原生一个代表记录；不把有限检查扩大为全游戏无bug，经验新效果没有追加原生战斗。下一继续其余普通剧目/节点与自然供给；其余23项、全命名模式/成熟EXE/Golden/离线长时/性能/Harmony仍未完成。完成文字晚于包，不为纯文字创建重复bundle，完整目标ACTIVE。

后续回归纠正：本报告的185汇总含一个遗留STARTED用例，它的结果早于本批最后的货币开战检查，不能作为末版通过证据。后续related-v1实际发现夹具被新准入拒绝，已只在自有夹具中明确模拟旧准入生成历史STARTED，恢复生产守卫后确认不能追加方案；单项补验通过，不倒写为当时已经通过。旧185汇总/所有XML和源码检查点保留，详[普通基础奖励报告](roguelike-base-rewards-2026-11-11.md)及.cache/rogue-base-rewards-20261111/final-v1/prior-check-scope-correction.json。
