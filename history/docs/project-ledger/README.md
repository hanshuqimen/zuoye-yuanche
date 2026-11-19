# TerraLocal 项目事实账本

统一保存需求、当前状态、历史、失败、依据与检查点。**完整保存，按需读取**；文件/Git/实际进程、检查输出、原生画面与远程回读优先于旧文字。

## 每次开始或恢复工作

1. 读本页、[需求的当前修订](REQUIREMENTS.md)和[简短当前状态](STATE.md)。需求未变化时，不反复展开原始全文及旧修订。
2. 只读STATE链接的当前系统/具体问题所需段落；先用`rg`定位，再取相应范围。不要顺带读取无关剧情、商店、旧模式或整份历史。
3. 核对该任务实际Git/相关文件与必要的进程或会话。共享迁移、认证、资源、备份等依赖确实受影响时，再读涉及的其他系统记录。
4. 旧失败/来源/检查点需查证时，用[INDEX](INDEX.md)、[EVIDENCE](EVIDENCE.md)、[CHECKPOINTS](CHECKPOINTS.md)定位具体证据；不全量加载。原始需求仍在[Prompt.md](../../Prompt.md)及[sources](sources)，新功能/验收审计按对应要求读取，不缩减完整目标。

## 更新与证据

- STATE只保留当前基线、正在做什么、实际运行状态、下一步与必要入口，保持简短。详细过程追加[HISTORY](HISTORY.md)和对应系统报告，证据登记到EVIDENCE/INDEX。旧STATE原文保存在[state-archive](state-archive)，不因精简删除失败或历史。
- 需求变化先更新REQUIREMENTS和下一步；实现/研究/失败/验证/提交/备份/交接前更新实际范围。STATUS/ROADMAP/CHANGELOG仍是摘要，不覆盖当前事实。
- 区分源码、自动检查、原生、发行物、官方依据、本地策略与QA夹具；局部通过不能推广成系统完整。未受影响的通过检查不为补记录重跑。
- 观察超时不等于任务终止；核对实际句柄/PID/会话，不凭旧标志重启。源文件、保存、发行物、失败副本与Git历史保持。
- 远程完成须实际回读SHA和新D恢复。权威索引`.cache/github-checkpoints/heartbeat-latest.json`及私有仓库首页；核对source_commit/readback_verified，后续文档不冒称已在旧包内。
- 原始客户端/资源/GameData、保存/数据库、收据、认证/私钥、日志/缓存及原生图片/代码页仅本地，不能因记录完整而进入Git。

建立账本前的全部修改无法补造追溯；[SOURCE_HISTORY](SOURCE_HISTORY.md)为建立时已提交历史。更晚以实际Git为准。
