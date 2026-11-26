# 当前状态与按需入口

2026-11-26 当前目标仍是完整本地服务端和成熟 Windows 交付，尚未完成。原版危机合约本轮进入主地图/节点导览，实际一次 getInfo；v2 17/v3 62 请求均200，0新战斗。页面缺旧赛季 entry/atlas 资源：冻结 V077 清单和APK只有常驻包，未改名冒充。原生战斗、结算、领奖/商店和回放仍未验。[当前联调报告](../crisis-native-client-2026-11-26.md)

已按原版反例修复本地符文提前解锁：新授予需关联临时图全部已核任务完成，空任务拒绝；旧授予和首次回执保留。61关联检查通过，冻结14457902首季四临时图各3任务、六符文30次HTTPS（12预期409/18成功200），冷重试原响应相同、两轮服务组有序停止，验证进程退出0。资格仅QA预置，实际首季已关闭。旧5个setup错误、5个业务反例和25日宽松策略保留。

当前无本轮仍需控制的模拟器或REA会话。v2私有收尾失败退出1，受控恢复退出0；v3正常收尾退出0、index1关闭、index0和现用/源指纹保持。REA M162851 1140字节确认真实领奖路由crisisV2/confirmMissions，枚举/批量消费尚未补齐；public close身份检查报错，子进程0/包装器1，随后精确PID/运行目录均不存在。失败和证据保持，未重建EXE。

下一先取得并验证该赛季资源及客户端加载路径，再接confirmMissions和一个原版战斗代表；不重打旧关、不恢复取消的剿灭。固定条件：仅index1/0063090c；APK/资源/数据/TLS/离线及8秒命令门槛保持；所有新增开发资料均限项目内。完整需求/各模式见[REQUIREMENTS](REQUIREMENTS.md)和[能力表](../current-capabilities-2026-11-18.md)。

源码HEAD接手仍为99e573d，保留21日独立配置及25日本地功能未提交差异；正在整理完整源码检查点。最新完整公开历史仍source ec9f1a6→main e1157d6（774公开/727源码/384历史，项目内恢复已核）；精选回滚分支checkpoint/crisis-v2-20261125的775eea4另含23变更和19恢复测试，不替换完整包索引。[检查点](CHECKPOINTS.md)

用户列出的22目录迁入.cache/moved/已完成，80,926文件/2,910,429,928字节原完整SHA核对、6 Junction及本地Git引用修复、20日再次回读保持；不为记录重复移动或重跑未受影响检查。[迁移](../workspace-directory-move-2026-11-19.md)。上一版实际验收发行物仍为源码721a26e，最新业务未打包；[发行物](../windows-backup-release-2026-11-19.md)。

本轮前全文已保存于[state-archive/STATE-2026-11-26-before-native-results.md](state-archive/STATE-2026-11-26-before-native-results.md)，更早原文、失败及未完成范围在[INDEX](INDEX.md)、[HISTORY](HISTORY.md)、[EVIDENCE](EVIDENCE.md)，不以本摘要取代实物。
