# 肉鸽生命输入研究与未开战会话复核（2026-10-24）

当前业务仍为3f897c9/6ac3e677；schema0024/70表，没有新增业务成功分支、没有新EXE。上个目标回合属于进展：取得M84576完整默认路径及v14加载对照、v15原生反例；未证明完整目标完成。

REA M84576 RoguelikeBattleManager.PreprocessLevelOptions：536/536字节，exit0，ev_dec38f001bebbad0e6b1306fa29d779dbffb07af4753e4184942bdc2ac4c7e8d。调用点M81854以inputHp/inputShield传入；默认路径先将二者相加写Options.maxLifePoint，再逐个应用有效藏品。LLMaxLifePointAdd默认路径对该字段加黑板整数。特殊条件分支将值设1，其完整适用范围未接纳。该输入过程不等于伤害/失败/中止/结算规则已经完整逆向。

纠正研究假设：M81854/84829/66420的三页加载代码与磁盘摘要相同。部分Ghidra截断来自小分析片段缺少尾调用目标，不是已经证明的运行时保护；撤回此前该说法。扩大对应目标后M84576默认完整；M66437 TakeSnapShot本体仍未完整线性解码，准备守卫拒绝，未启动其提供器。不能用包装方法或完整指令数替代实际统计语义。

静态M81871实际exit1/cleanup_incomplete，保留partial_observation；随后查明报告的LinuxPID574已不存在、该socket不在/proc/net/unix，未杀其他进程，不把此操作记成功。其他三次静态操作exit0但有Hotfix/尾调用或默认路径缺口，不称全客户端逆向。

首次尾调用准备脚本误建O(n²)地址表，未启动提供器。第一次停止守卫因venv父/子两进程拒绝，未终止任何进程；确认同命令与父子链后仅停止所属叶13596（父4540），后续守卫因缺报告exit1。旧脚本、失败记录保留；线性字典修正后4.67秒准备到M66437解码守卫。未修改原客户端或游戏数据。

v14：仅三页代码读取，零UI输入/零战斗/无rlv2请求；13请求全部200，仅local_sessions变。正常exit0，所属服务/ADB/index1正常关闭；57其他账号表和输入保持。加载3页各4KiB仅文件映射代码，无堆/认证读。来源3f897c9，新D数据70表由旧69表只增加结算表/版本，原数据保持。

v15：计划第一次肉鸽战斗，实际止于主题Continue入口，33请求32×200和1×501（GET /protocol/cadpa-age.txt），没有rlv2调用，普通/肉鸽战斗均0。2026-10-24复核执行句柄2289缺失、所属源PID27196不存在、18443无监听、ADB进程0、index1停止；没有native-results.json，所以不能宣称辅助正常cleanup或推断结束原因。存档integrity/FK正常70表，仅local_sessions变，47受保护输入和57其他账号表保持。第一次独立审计错用了account_id<>1且漏accounts/operator关联表，54对57断言失败；改用原辅助的相同account2口径后57项相等，保留失败。

本地证据：.cache/rogue-settlement-20261023/{rea-hp,rea-hp-loaded,rea-life-complete,rea-life-options}/；.cache/rogue-native-20261023-v14/及v15/reviewed-results.json。资源、代码页、官方投影、数据库与原生截图不进入Git。

下一步从已停止v15复制新D目录，继续同一MAP_READY，不重复初始化，也不把尚未实际发生的肉鸽战斗算成已测。只对首次实际开战/结束做代表性核对，取得明确的生命与结束数据后批量接同类规则。年龄说明501登记待修。剿灭v35仍不恢复，完整主题、全模式和成熟交付目标继续。
