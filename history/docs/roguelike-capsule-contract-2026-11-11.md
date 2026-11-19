# 首主题剧目合同审计

基础酒窖一个原生代表通过后，继续查剧目对应的持久状态和消费路径，没有重开模拟器或重打关卡。当前业务仍为022c4aac、198个Python文件、schema0037/78表。酒窖结果与恢复记录见[原生阶段报告](roguelike-recreation-cellar-2026-11-11.md)。本报告先记录已验证依据，未接线部分不能视为已实现。

实际导入e915的19表、v077/77.6.0/client_verified=false；冻结客户端国服2.7.71/V070，不冒称全部同版。只读QA32保存核实rogue_1/NORMAL0、创建时间1792645099，主题已开始并归档。具体主题有26个CAPSULE物品、26条capsuleDict、一项与剧目相关的FEATURE机制物品、四个引用该机制物品的事件选项。计数只是此版本此主题，不推广其他模式和未来开放状态。

`rogue_1_capsule_26`才是剧目，type=CAPSULE、subType=RED_CAPSULE，名称「猩红《欢欣鼓舞》」，maskType=ENTERTAINMENT。物品usage写明下次进入幕间余兴获得3目标生命、希望和源石锭，结束时50%概率返还节点开销。这是本地导入文本依据，尚未证实后台概率实现、取整、叠加、消费与返还时序。`rogue_1_capsule_26_f`是FEATURE机制物品，description为「返还资源」。它被choice_ent3_6引用，选项描述返还消耗的全部目标生命，转scene_ent3_5解酒药片叙事。不能因两者名称相同，就把FEATURE当作普通收藏品入库，或向所有无剧目的酒窖默认开放该分支。

冻结元数据`official-index.sqlite3`的SHA-256为30c555d4479d4a0f708b9fc61aa4ecfeb945a169e4a82586e31d243afdaa4804。CurrentData.Capsule字段为id:string、ts:long、active:bool；CurrentData.Buff.capsule为单个Capsule对象，Inventory没有capsule字段。OuterData.Collection.capsule则是独立的解锁字典。服务器当前snapshot明确返回buff.capsule=None，结束和放弃capsuleList为空，无剧目持久化/获取/消费/图鉴/结算链路，不能称支持剧目。部分UI字段offset含保护值，未将这些值用于内存寻址或字段布局推断。

静态研究选择四个具体消费者：M150628 Create 0x3e05b30/456字节、M150629 Create 0x3e05d68/484字节、M160866 LoadData 0x4096f64/260字节、M33726 GetCurrCapsuleId 0x44fbac8/240字节，均完整线性解码；这不证明语义完整或热更新分支。构建只含冻结文件四个代码页的隔离ELF，20480字节、75个完整种子，SHA-256 a8f2a151f1f4a92df40e4a56521cadfeda26a4acaea3534386e7ef9223ed468a。未读取Android、堆或认证数据。REA仅stdio，运行目录及临时/缓存放D盘。

本地入口`.cache/rogue-capsule-20261111/data-contract-v1.json`记录实际表、具体运行身份、26物品与关联选项、字段、目标方法以及198Python/原生最终数据库/settings/菜单种子/检查点索引的保护摘要。`rea-static-v1`及`mcp-capsule-v1`保留静态解码、RPC和后续结果；这些官方数据与代码片段仅本地。下一先补REA默认消费与边界，再确定版本化剧目获取、单个当前对象、节点激活/失活、返还资源日志和结束历史设计；未知自然池与概率保持独立缺口，不由QA结果取代。

REA四个实际返回已逐项核对。M150628默认在capsule非空时用其id查询主题物品，检查类型值0xe，向视图写名称、usage、active、ts和颜色；证据ev_1cfe72b844d46303da9e7bfcb00da0712f6aac198bfa950bf6f8cda9b9b1e75e。M150629是显式id/active/ts重载，拒空id，使用相同物品查询与类型检查，证据ev_dfca365574f868d90d52618c5154a3c159dbcd27179fbb90e70cadca8e7fd4cc。两个默认分支可读，保留重叠全局警告，Hotfix只见委托调用，未核执行内容。没有从数值类型或物品描述推导后台效果。

M160866默认读取当前探索的buff.capsule，空时不建剧目视图，非空时传给M150628；尾部及Hotfix分支有bad-instruction截断，证据ev_bd101d966dbf6b5a1420b199b63d743bb7cccdcbc660486747a0b0cf95d4c507。M33726默认在对象存在时返回capsule.id，否则null；未在已见默认路径检查active，这不等于证明inactive仍生效，证据ev_a5fb18b2b863e3547eaf43861665ab51c8390f5f51f00eeaf52043a63741f9cb。其Hotfix分支同样截断。两处截断具体涉及隔离页外callee，不能据此声称已完全逆向或擅自读取进程堆。

此主题26条mask分布为BATTLES8、INCIDENT4、SHOP4、REST4、ENTERTAINMENT2、BATTLE_ELITE4；四个FEATURE选项分别返还微型舞台/珍品处理者源石锭、酒窖生命、鼠胆神偷希望及等量上限。它们需要各自节点的开销账本与结果时序，不以酒窖生命反推所有玩法规则。文本中的50%仍缺后台实现证明。

REA会话49359实际退出0，server退出0，隔离ELF字节保持。公开close_binary返回cleanup_incomplete，理由是owned launcher身份java与期望绝对路径不符，不能记为公开关闭成功。随后实际核对Windows30276/33492与Linux497均缺席；没有强杀或打开新分析目标。`.cache/rogue-capsule-20261111/verification.json`记录四份证据、限制、公开失败及实查退出，198Python、原生最终DB/settings、原菜单种子和当前检查点索引摘要均保持。本阶段0Android/游戏请求/业务改动/新EXE，237项旧检查未重跑。

研究已收尾，当前无待续原生或REA会话。下一实施须版本化保存剧目获取与替换、单个当前对象、mask对应节点激活/失活、该节点累计花销与一次返还、图鉴/结束历史和冷启重放；旧保存无剧目的投影与摘要必须保持。返还分支先采用有证据的显式配置，未知自然池和概率继续单列。当前尚未实现这些功能，也未新增私有bundle；本阶段只有研究文档，现有业务源码仍在已核验的私有c9a619e检查点。

后续范围纠正与实现：[普通剧目流程报告](roguelike-capsule-flow-2026-11-11.md)。猩红剧目需较高难度条件，当前NORMAL/0不开放其返还分支；先完成普通《初晓》/《金羽兽》的领取和节点生命周期。上段“尚未实现”保留为研究收尾时状态，不覆盖新报告的具体实现/验证边界。
