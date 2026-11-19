# 默认地图发布成本定位与修正（2026-11-12）

完整目标ACTIVE。上一默认基础供给source9d46062/业务c84840e4、179相关检查、真实37用户78表恢复及私有a8ecf67回下载/627文件303历史新D恢复已完成；本轮不重打任何关卡或剿灭。继续修实际耗时，不能把未核准的本地自然供给条款写成官方规则。

profile-v1/30496实际exit0：只在新D复制真实37用户/78表保存，全部原视图/原始行先核同，再新增QA38正常初始化。保留before-publication.db和完整未发布用户视图，在服务器本线程调用真实Runtime.mutate/rogue-finish-initial和原处理函数，以cProfile覆盖领域计算；随后同键HTTP重试与协议适配结果完全相等、数据库不重执行。没有伪称cProfile捕获了TestClient另一个工作线程。

冻结19表e915/v077/77.6.0/client_verified=false、rogue_1/NORMAL0/保存时钟1792645099，独立生成48节点、47内容分配；当前MAP_READY，0新战斗/Android/原生/REA/EXE。10HTTP全200，所有成功增量一致；完整38用户78表真备份/重启/新D恢复同，旧37用户25战斗及全部旧行保持。

带分析器的一次发布6466.189ms；其内publish6287.835ms、内容validate366次、allocate358次/累计5287.976ms。同一不可变配方和图被在47次节点准备及相关重放中反复编译/生成，是具体主因，不只是根据总时长猜测。单次sync带分析器76.746ms，allocate只有1次，不能从此认为所有普通接口或P95达标；分析器开销也不能与上一无分析器2.272s直接作加速比。

本批仅修改domain/rogue_content.py：准备一次发布时建立私有会话范围，缓存纯编译/生成材料。每次命中仍比较账号/数据对象/同一ORM对象、探索与地图身份、方案摘要、完整实际plan和graph字节，包含ORM未跟踪的JSON原位修改；不缓存已有节点行的验证结论、不跨发布/请求/事务、不用全局LRU保留GameData。局部发布标志仍在最终完整绑定检查前清除，退出或异常均清除纯材料缓存。旧方案/地图/收据/业务规则摘要不修改。初版时尚未针对检查和同保存对比，最终结果见下，不倒写初版即通过。

证据.cache/rogue-default-profile-20261112/actual-v1/{verification.json,publication.json,publication.pstats,sync.json,sync.pstats,before-publication.db,before-publication-user38.json,full-users38.json,working,restored-new-d}。数据、QA口令、保存、日志/分析器输出仅本地，不进Git。初版下一步为验证JSON改动/遗漏仍拒绝和同保存测候选；已执行的范围见末节。

## 当前最终验证范围

业务0b7b0c14108fa677efbce1b040e8adf2fdccbad3c181361ebab3d2383b2f2dfd/201Python/0037-78，仅一个业务文件和一个新测试文件。54个不同相关用例最终通过（6新、48受影响既有），以tests-v1.xml和tests-fix-v2.xml逐用例最终结果归并；不把旧179用例机械地列为此业务源码全部重验。两文件Ruff与diff检查通过。

六个新检查包括单次发布只编译/分配一次且离开范围后不复用、未跟踪plan/graph原位损坏拒绝、删事件/改商店价/改战斗方案仍全回滚，以及成功/异常后缓存和局部标志清除。首轮52通过/2失败：新测试把干净ORM对象的JSON原位改坏后没有保存强引用，SQLAlchemy弱身份表可释放该对象，最后查询重新取得未被改坏的数据库值，故未发生预期拒绝。只修测试保留强引用至最后查询，三种live-row故障v2全部拒绝/全表回滚；没有再改生产守卫，失败XML保留。

candidate-v1/62825实际exit0：从同一QA38的before-publication.db和同一已生成本地会话继续，没有创建新账号/探索/战斗，不用新随机场景作比较。相同分析器下一次真实发布6466.189→767.479ms，总allocate358→6（发布范围内1，其余为范围外校验），publish本体约6287.835→616.230ms。单次带分析器sync65.692ms。该结果证明具体重复计算减少，不是无分析器接口延迟或完整P95/内存目标达标证明。

完整38用户视图与基线逐项完全相同，完整保存MapDraft全部字段也相同；三类内容绑定的其他全部字段相同，仅排除每次生成的内部行UUID及由其派生的rule_hash，不能写成两次数据库原始字节相同。候选自己的38用户78表真备份恢复/冷重启/新D恢复严格相同，原37用户25战斗和全部旧行保持，来源保存/资料/保护输入不变。一次HTTP同键回读与直接协议结果完全一致、无重执行写库。

最终证据.cache/rogue-default-profile-20261112/{tests-v1.xml,tests-fix-v2.xml,candidate-v1/verification.json,candidate-v1/publication.json,candidate-v1/sync.json,final-v1/final-checks.json,final-v1/verification.json}，所有本地失败副本和基线保留。尚未新增默认地图原生视觉、REA、EXE或断网长时证明；默认内容的本地条款/不完整目录也没有因此成为官方规则。下一保存源码私有回读点，再继续默认原生消费和准确供给，而非反复同关测试；完整目标ACTIVE未完成。


2026-11-12 发布材料源码私有回读完成：source6dd2fd6df657dde9be9093aef54a823bcdc6be83/业务0b7b0c14/201Python/0037-78→privatece757ebdb4ded7955de5b42c05e15b9be54e2a70，父a8ecf67/tree5006fe75503d6cea16f1b2222290f863ac931117。bundle2898967字节，SHA256 57817a6c160398b687f1acab553bce223cfe8e496c9e863284805c2b7ac0627a，Gitblob1117a91962e6ef1b3ab35695388bc89291004cf1。629源码文件/305完整历史，新D完整tree/blob/Prompt/fsck/clean同；631历史路径3427UTF8 blob扫描无禁入/凭据标记。旧251非README项保持，README新增1098字节最新范围，旧173441字节全文为完整后缀；远端254项。

普通Git本次禁交互probe128无登录/无ref；连接器expected_sha+force=false续私有main，非源码分支直推。私有标志/ref/父/tree、manifest及README全文实际API回读相等；授权网页精确提交Download raw file真实事件入站，双hash后仅本次新C临时下载移D，新D恢复actualexit0。未改浏览器权限、读凭据或访问被阻止8080。权威heartbeat-latest/local-latest同本次upload-verification，旧索引previous-*及全部旧包保留；其余保存/客户端/资源/资料和业务源码保护输入保持，另有protected-inputs-after-index-rotation.json。

本地.cache/github-checkpoints/publication-material-20261112/{prepared.json,old-remote.json,readme-preservation.json,pending-commit.json,api-readback-summary.json,remote-meta.json,upload-verification.json,protected-inputs-after-index-rotation.json,received-web,restored-remote-6dd2fd6}。本包54相关检查（6新）、同QA38未发布保存带同分析器6466.189→767.479ms/allocate358→6、完整38用户视图/MapDraft同基线及候选38用户78表真恢复入包。0新探索/战斗/Android/原生/REA/EXE，未称无分析器P95/内存/自然规则/全模式完成。完成文字晚于包，不重复文档bundle；下一默认原生消费/准确供给，完整目标ACTIVE未完成。
