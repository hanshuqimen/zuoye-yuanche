# 发布验证

2026-11-19 Windows 包的备份恢复、UTF-8 管道、冷启重试及启动窗口备份已在合成存档实际验证，并进入本机新的独立发行目录。1,080 文件和 MIT 清单匹配，27 份旧 EXE 保留。用户指定的22个目录已完整迁入项目，所有新增开发及恢复文件限于工作区；旧私有仓库已按当次确认删除。完整玩法、原生客户端、断网和 HarmonyOS 验收仍未完成。

实际摘要见 [Windows 验证](validation/windows-backup-release-20261119.json)。早期失败与已通过结果继续保留，未重跑全量或游戏关卡。

## 后续备份修复的定向检查

源码 9ea5f815abd2e6ef3b43e7a3476013914000ba7f 的 211 个不同相关用例最新结果全部通过，原先 15 个失败均已复验通过；新增 11 个备份用例。没有重新运行全部检查。实现、旧迁移夹具和保留的中途失败见[修复报告](docs/backup-domain-validation-2026-11-19.md)与[逐项复验结果](validation/backup-recovery-20261119.json)。原生及新 Windows 包仍待验收。

## 首次公开版本的完整检查（历史结果）

2026-11-19，使用独立的 Windows 发布副本和 Python 3.12 执行全部 3,203 项检查。3,187 项通过，15 项失败，1 项因缺少可选的冻结游戏数据而跳过。逐项结果见 [检查结果](validation/results.json)。

此源码仍处于开发阶段。失败项中，11 项涉及旧版迁移的表数量断言，4 项损坏备份检查没有触发预期的拒绝。这些问题保留为下一阶段的调查项。

实际本机 HTTPS 验收覆盖健康检查、登录、写入、全量同步、备份、停止以及将备份恢复到新文件。四次 HTTP 调用均返回 200，恢复文件的 SHA-256 与回执一致。

第一次发布检查遇到测试辅助缺失。补齐合成辅助后，Windows 深路径限制使构建检查提前结束。改用 D 盘短路径后按原集合继续，三批记录覆盖全部用例，每个用例只计一次。原生客户端和新的 Windows 发行物仍待验收。

## 待核对的失败项

| 用例 | 观察结果 |
| --- | --- |
| tests/test_rogue_direct_migration.py::test_schema32_elite_offer_scope_and_all_old_columns_survive_atomic_migration[False] | 旧版表数量与断言不同 |
| tests/test_rogue_direct_migration.py::test_schema32_elite_offer_scope_and_all_old_columns_survive_atomic_migration[True] | 旧版表数量与断言不同 |
| tests/test_rogue_elite_migration.py::test_free_training_history_and_all_old_columns_survive_0031_or_atomic_rollback[False] | 旧版表数量与断言不同 |
| tests/test_rogue_elite_migration.py::test_free_training_history_and_all_old_columns_survive_0031_or_atomic_rollback[True] | 旧版表数量与断言不同 |
| tests/test_rogue_floor_drafts.py::test_corrupt_future_candidate_backup_leaves_live_database_intact | 应拒绝的备份被接受 |
| tests/test_rogue_floor_progress.py::test_corrupt_cursor_backup_never_replaces_live_save | 应拒绝的备份被接受 |
| tests/test_rogue_paid_training_migration.py::test_0029_free_history_and_all_rows_preserved_or_transaction_rolled_back[False] | 旧版表数量与断言不同 |
| tests/test_rogue_paid_training_migration.py::test_0029_free_history_and_all_rows_preserved_or_transaction_rolled_back[True] | 旧版表数量与断言不同 |
| tests/test_rogue_temporary_migration.py::test_paid_history_and_all_rows_survive_0030_upgrade_or_atomic_rollback[False-training_runtime0] | 旧版表数量与断言不同 |
| tests/test_rogue_temporary_migration.py::test_paid_history_and_all_rows_survive_0030_upgrade_or_atomic_rollback[True-training_runtime0] | 旧版表数量与断言不同 |
| tests/test_rogue_training.py::test_0028_migration_adds_only_empty_history_and_null_target_and_is_atomic[False] | 旧版表数量与断言不同 |
| tests/test_rogue_training.py::test_0028_migration_adds_only_empty_history_and_null_target_and_is_atomic[True] | 旧版表数量与断言不同 |
| tests/test_rogue_visits.py::test_0025_upgrade_and_failure_rollback_keep_old_rows | 旧版表数量与断言不同 |
| tests/test_roguelike_battle_start.py::test_corrupt_backup_and_missing_current_table_preserve_original | 应拒绝的备份被接受 |
| tests/test_roguelike_map_drafts.py::test_invalid_candidate_backup_is_rejected_before_touching_current_save | 应拒绝的备份被接受 |
