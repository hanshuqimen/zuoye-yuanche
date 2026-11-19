# 2026-10-22 独立开发构建与打包验证

## 实际发行物

来源提交180320474ac818642f7f085262788b30402f1614，业务指纹6f90c38cfdfa41e922c0f11937afac100778097cd68a729734b3ef6fdea5a638。使用现有隔离构建器，工作/输出和新缓存均在D；没有修改构建器或业务代码，也未重跑旧1194全量集。

新程序：`dist/releases/20261021T224516.553837Z-e5ec1dde/TerraLocal/TerraLocal.exe`，SHA256 `b0c5a810f98eadfc9ade8b9952365e537c423a65cf9ab5484fd1988028fba1c8`。构建编号是UTC10月21日22:45，本地日期为10月22日。1079个清单成员及清单外仅build-manifest.json的精确成员集合均核验；未混入存档、官方客户端/资源或GameData。client_verified=false、mature_release=false保持，这不是完整成熟交付。

旧已原生验证EXE仍是20261015T130657.442528Z-8fe6015b版本，不覆盖。构建及接口验证后，旧EXE、产品数据库/设置、v35数据库及侧文件共6项SHA保持；并未对所有历史输入重新跑不相关检查。

## 新EXE的命令行验证

在新D目录使用打包程序执行7条入口：version、help、gamedata import/activate、doctor、drops compile-penguin、drops import、drops show，全部exit0。只复制18表manifest明确列出的表和原版本字符串作为本地输入，重新导入得到原指纹f44199a7d34a82bdbb232674db3a3cdf9d7958230217fce3960ccafd351b7406；本地旧Penguin样本编译结果150关，验证首次干员奖励和SUB映射的新版编译器确已进入EXE。doctor数据库ok，但ready_for_play/client_verified仍false，不从入口成功推断全部可玩。

首轮检查脚本固定UTF-8读取管道，帮助文字实际使用Windows本地编码，触发UnicodeDecodeError。保留初始脚本、目录及输出；在新重试目录先保留原始字节，再严格尝试UTF-8/GB18030解码，未修改产品校验或把乱码替换成成功。帮助及含中文原因的编译报告按GB18030读取，其他此次输出为UTF-8兼容字节。不能因此声称所有环境输出均固定UTF-8。

## 新EXE的接口验证

使用全新自有合成GameData与存档、固定QA时钟和两账号，启动实际EXE的serve；后台Console显式隐藏，只访问该测试游戏端口。未打开管理页面、未绑定/启动模拟器、未读官方认证。客户端连接组件在无绑定状态，不调用Android。HTTP为仅loopback的合成接口夹具，不作为真实TLS/离线/原生客户端验收。

12次POST覆盖本地登录/同步、所需干员阶段不足时拒绝（400且不扣理智）、正常精英化、开始/编码结算、剧情完成、RETRO与类型化奖励任务领取/同步；11次200，1次预期400/STAGE_REQUIRED_OPERATOR，无未知路由或500。验证剧情state3、剧情物品2、家具实体1和新增干员，不将服装塞进普通inventory。

首轮合成夹具没有把掉落目录写入磁盘（测试fixture原先只赋给内存Runtime），实际EXE正确503/DROP_RULE_MISSING拒绝，未进入战斗。该失败副本/脚本/结果保留，正常退出0、待结算0、53其他账号表保持；不能改写成第一轮全绿。在全新重试目录准备持久化的单关自有custom掉落夹具后完成上述流程，没有更改产品逻辑或伪装官方概率。

只向本轮EXE的独立隐藏Console发送Ctrl+C，实际正常exit0，两服务Application shutdown complete，未使用强制终止；CIM没有剩余TerraLocal.exe，两个测试监听端口可重新绑定。待结算0、SQLite integrity/外键通过，53张其他账号表保持；随后源Runtime重开59表一致。源Runtime重开不是原生客户端冷启动验证，也不等于再次完整服务/客户端验收。

## 记录与下一步

证据在`.cache/release-integration-20261022/`，包括build-result.json、构建日志、cli-result-retry.json及原始字节、两轮api-result、服务退出日志、integration-verification.json、protected.json和保留的合成副本。原始表、存档、凭据及二进制发行物不提交Git；来源1803204已私有回读/新D恢复317文件55提交，当前记录以后续检查点索引为准。

此构建整合普通关卡目录、剧情关/章节推进、候选任务与干员前置等最近源码；其原生动画/视觉、完整抽卡、其他战斗环境、集成战略/卫戍协议/剿灭/危机合约等高级模式、Golden、断网、两小时、性能及HarmonyOS仍未完成。下一步按完整主题推进集成战略匹配数据/协议/持久化，不再重复已经通过的同一关卡游玩。
