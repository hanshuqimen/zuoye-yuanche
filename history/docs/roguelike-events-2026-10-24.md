# 肉鸽事件合同与图解释器（2026-10-24）

## 当前实现和边界

现有产品把地图路径/游标直接从肉鸽战斗行生成，不能靠伪造战斗行接非战斗节点。下一步必须独立保存节点访问/事件决策，并把场景与战斗纳入统一可达路径和重放校验；不能只加selectChoice的空200。此依赖未完成，**本阶段不称事件可完整游玩，实际selectChoice仍501**。

新增首主题场景目录、显式事件图编译器和纯解释器，及GameData惰性入口。编译器逐一检查场景/选项、完整选项行摘要、指定后继、条件字段、效果边界、不可达节点、死循环和退出路径；运行器从原始资源及有序决策重放，资源支付/效果在同一次转场计算，拒绝跨场景选项、历史非法、余额不足和溢出。不执行文案表达式，不从ID拼接事件，不把NEXT_PROB/TRADE_PROB当确定效果，不默认随机概率。

使用dialogue-systems技能的自定义图方式；只保存文本ID，叙述/美术留在导入客户端表。条件与变量、显示与转场分开；后续DB事务驱动须调用decide并持有原始资源/决策，不能接受客户端提供的余额/当前场景/结果。幂等和持久化尚由下一步事务层处理，不宣称纯解释器已经防止跨HTTP重复发奖。

冻结e915675d实际目录为172场景、152选项：LEAVE3/NEXT46/NEXT_PROB9/TRADE89/TRADE_PROB5，全目录结构检查通过。额外编译三个完整的固定收益图适配：扎营HP+3、讲故事的人希望及上限+2、善良的木偶源石锭+5；初始一选项、结果文本、离开。效果数值与[PRTS事件一览](https://prts.wiki/w/傀影与猩红孤钻/事件一览)及冻结选项行核对，各行SHA绑定，变化就拒绝，不混入官方对白/资源。显式图是当前适配依据，**不证明这些事件的官方出现池、楼层/模式/当前开放或概率**。不会因为172/152结构通过就将全部事件标为玩法完成。

三个图都完成纯计算转场与资源结果检查，不是产品HTTP、数据库或原生效果验收；结果页离开路由还需真实分支核对，不能套用初始finishEvent。

## v19仅用于协议与代码研究

来源940436b/业务a2a9953a。新D目录完整复制v18停止存档71表，原数据/输入保留；只在QA辅助的syncData响应中，将已保存v10地图/两干员投影为PENDING+SCENE(scene_hp_enter，choice_hp_1与choice_leave=true)。真实数据库保持v18已经SETTLED的探索。该显式夹具不属于产品代码，不伪称自然到达事件或移动成功。

原生显示扎营背景/文字、HP4/希望3/金币6、两选项；点击“沉入梦乡”出现确认面板，确认后发POST /rlv2/selectChoice，请求字段为choice；旧产品未实现而返回501并出现原生提示。辅助遗漏记录choice的具体字符串，未补造抓到的值；choiceId到请求字段的映射由冻结metadata和REA另证。true在此夹具中表现为可选择，不推广为所有条件/隐藏选项语义。

16游戏请求15×200+1×501，仅local_sessions变化；错误类型计数空不抵消501。没有新战斗、奖励或事件持久化。57其他账号表/全部保护输入保持。原native句柄48973实际exit0，所属服务/ADB/index1正常关闭。截图08/09/10只证明QA场景和确认消费。

## REA依据及失败

原M150477 SendSelectChoiceRequest磁盘解码缺口，准备守卫拒绝、REA提供器未启动。真实确认后，仅读取index1两页文件映射代码0x3dff000/0x3e00000，APK/ELF/硬件/8秒守卫保持，没有堆/认证读取。两页合并SHA e32d8c02714672da8e9b04a242cf2ba632525a58c60fd5f183f12305967d60fc。

M150477 592/592、REA exit0、ev_3b53178a9d92e1144101a446a33689b7ec2177186eb7c65858c0bed399b81624，方法体SHA cf860c0185cfeffc4ad4deaec2ffe725b4d353704160c8c93428a44d34da1527；默认构造RoguelikeSelectChoiceRequest（metadata M28333/.ctor/0x3f3b544）并把choiceId赋给请求，另有onComplete回调。M150479 SelectChoice 464/464、exit0、ev_903e12556de754a5e0ffcf31abf2ef6681202e81ac67442028982fe5d23e5b98，默认守卫后调用上述发送；Hotfix分支截断/符号警告保留，不称完整函数或全客户端还原。

首次加载代码切片准备错误地要求目标函数跨两页，实际592字节都在第一页末尾，守卫拒绝、无提供器启动；失败脚本保留，修正为包含目标的实际已读页范围后成功。前两次准备失败后PowerShell仍调用runner而得到缺报告FileNotFound，均无提供器启动；后续调用已按退出码顺序执行。错误搜索通配路径/不存在文件只影响研究定位，未修改产品/存档。

## 检查与下一步

28项解释器/图/条件/资源/退出/循环预算/指纹检查0.09秒通过，Ruff0；前25项及重放后移位的2项0.07秒有重叠，不累计。1条既有Starlette警告。schema0025/71表未改，不重跑无关旧检查，无新EXE。

本地证据：.cache/rogue-events-20261024/{validation.json,data-program-validation.json,program-tests-final.txt,relocated-checks.txt,rea-choice/,rea-choice-loaded/,rea-dispatch-loaded/}；.cache/rogue-native-20261024-v19/{reviewed-results.json,fixture-source.json,native-results.json,requests.jsonl,loaded-code-receipt.json,screen-08.png,screen-09.png,screen-10.png}。官方代码页/导入表/截图/DB/运行日志仅本地。

下一步在本解释器之上接独立节点访问/事件账本、拥有权/可达路径、selectChoice/结果离开及事务/同步/重启；再同类扩展固定交易、随机效果、藏品/券/商店/楼层。不得回到重复游玩旧关或剿灭v35。完整主题和完整成熟服务器目标仍active且未完成。

新检查点预登记.cache/github-checkpoints/rogue-scenes-20261024/；本阶段提交前最近已完成远程来源940436b（367自有文件/87完整提交），新来源须按实际回读/新D恢复索引核对。
