# 多楼层地图方案保存（2026-10-25）

按用户效率要求，不恢复已取消剿灭、不重复旧关或商店原生购买。本阶段在商店后结算与楼层客户端模型依据上，补齐整段明确多层方案的持久化；没有用未知默认池补成正式供给，也没有给未确认的换层路由返回空成功。

## 源码范围

`rogue_floors.py`的FloorSequence保存完整有序Plan，策略rogue-explicit-floor-sequence-v1固定引用rogue-layered-map-v2，避免以后默认版本变化重算旧图。首层沿用原种子，后续层种子绑定版本、数据、原种子、楼层索引与自身方案；改未来方案不会改变前面楼层的生成输入。首层须zone_1，每层继续验证实际区域/关卡引用，portal不套普通图。最多16层/4096候选是本地预算，不能称官方限制。明确重复区域可用于QA方案，不能据此声称官服路线合法。

复用RogueMapDraft现有plan/graph JSON和独立新策略，不增加schema或表。prepare_floors一次事务写全部楼层，read_floors只读当前账号的探索；相同方案不重抽，不同未来层、单层/多层互换、截短方案都拒绝覆盖。启动前与备份候选回读检查全部未来图，拒绝未知字段、错索引、缺权重、越区或错误种子；不只看首层。旧单层v1/v2及100键仍走原校验，不写回转换。

已有游戏驱动仍只消费第一层。finishEvent只激活首层，同seq重试或新seq重试不换层，syncData不暴露未来图。事件/商店/普通失败/V3结束在该序列的首层可复用原事务事实；未实现真实跨层游标、按zone的战斗身份/资源时间线、层奖励与结局资格。保存六层方案不等于六层已可玩。

## 实际验证

首批18项8.56秒通过，新增首层scene→shop→普通失败→V3结束组合后，62关联项35.98秒通过；两组重叠，不相加。覆盖单层/多层互换拒绝、不可替换未来方案、双Runtime并发、失败事务回滚、12种未来层损坏启动前只读拒绝、候选备份损坏不碰当前库、delta/初始交接/新旧seq、旧schema和100键兼容。战斗与结束组合用脱敏作者HTTP记录，未新增实际战斗。Ruff首次导入顺序告警已修正，最终零；一条既有Starlette弃用警告保留。

冻结CN2.7.71/build190/resource26-09-22-07-47-20_6c71fa、19表e915675d8d8a1cc97df8fa46eed27ef1bdaa9d1b0fdb07461dcabda36271ae29；NORMAL/0，QA固定时钟1800000000，主题归档仍可玩，不能把首页展示截止当关闭。六个具体区域zone_1..6的普通引用数5/5/8/8/8/2逐层采用已接纳区域目录。等权池、三列几何、额外边2500均为明确QA，不是官方概率或结局开放证明。实际wrong future-region在写入前ROGUE_STAGE_REGION拒绝。

新D测试存档12个HTTP全200，所有delta等于全同步；准备六层后尚未激活的完整用户状态不变，交接后只zone1/position null，同seq/newseq均不前进。全部六图重开相等，备份恢复及另一新D目录73表完整相等，账号隔离、普通资源/进度保持，普通与肉鸽战斗数均0。实际停机v23在另一个新D目录重开73表全行不变、完整rlv2等于当时末次原生快照；74保护输入保持，18443前后关闭，无Android/新EXE。

业务3ebf64a4b21c26a5e5cd1eb35f734c6fbf26991b9ed56d282f61ceaff68a0475；执行句柄86122/53195/18504均真实terminal exit0。本地.cache/rogue-floor-drafts-20261025/{tests-first.txt,tests-related.txt,frozen-validation.json,frozen-six-floor-save,restored-six-floor-save,reopen-real-v23}。上轮v24只是第二层同步QA投影，本阶段没有重复它或扩大成换层原生成功。

## 失败与下一步

恢复时若干路径检索误用了不存在的rogue_path.py、runtime.py、backups.py、rogue-map-storage目录及PowerShell不支持的花括号展开；用rg --files核对真实路径后继续，未据空结果得出产品结论，也未修改存档。首次账本补丁用了不匹配CHECKPOINTS标题而整批拒绝，确认零修改后按真实标题重做。辅助脚本的语法/无效条件在运行前审阅移除，未记作运行通过；实际冻结辅助首跑退出0。保留这些失误和既有测试/原生失败。

下一步核对实际终点完成/过层请求与pending条件，并实现独立持久游标、按层节点/战斗身份和跨层重放；不从无字段FinishNodeRequest猜路由。正式供给/隐藏层/结局、藏品效果、其他模式及完整成熟EXE/Golden/离线/两小时/性能/Harmony目标继续保留。

## 私有检查点

2026-10-25多层方案检查点6485631完成：私有上传4402c360、索引a1d2817a；精确提交网页raw下载SHA64bf8a0f057a52f18d47eb6d47dcd6ac042d28b904da899d26408068d53501f2，新D恢复391文件/100提交/完整历史/fsck/Prompt相等，句柄87068真实exit0。禁止路径/凭据标记0，原152根项及索引旧正文/153非README项保持；连接器大文件正文空未代替字节核对。实际索引.cache/github-checkpoints/rogue-floor-drafts-20261025/{upload-verification.json,checkpoint-web-proof.json,restored-remote-6485631}及heartbeat-latest。普通源码分支推送未宣称；新领奖入口业务1f1d087f尚不在648包。
