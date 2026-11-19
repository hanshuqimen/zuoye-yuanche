# 首主题自然商店前置：支援道具合同

基础资格21项与原生058代表已完成相应范围，私有检查点66e7175实际下载/新D544文件221历史恢复同。完整目标仍ACTIVE/未完成；本项不重打旧关、不复购已有代表。

当前正常报价目录只覆盖藏品，不能据此生成全部自然商店。实际19表e915/镜像a550f5e、v077/77.6.0/client_verified=false，冻结CN2.7.71/V070。当前rogue_1/zone_1为迷雾歧途，六个ACTIVE_TOOL物品分别映射六个traps记录（itemId/trapId/trapDesc）；它们不是RELIC，现有current.inventory.trap投影固定null，没有实现持有/替换或战斗道具输入。不能把藏品表直接套给支援道具，也不能只改图标声称战斗有效。

## 2026-11-01三项消费者已取得

同一冻结静态ELF两页构成12288字节工件ccbb97bc9e7cb39a9f11cdf71d92be99b6119829935118373be448f7ba5d4228，29完整种子。M33727 GetCurrTrapId 192/192，ev_494edf04837487d64f695f5682488b8c039a4f63119a5aa0bd4ca67bc8ffae9e：默认先EnsurePlayerRoguelike，再读PlayerData.roguelike.current.inventory.trap；非null时返回id，否则null。没有由该函数计算支援道具战斗数量。字段声明CurrentData.Inventory.trap偏移48、Trap.id16/ts24与实际指令一致；这与后期视图损坏偏移分开，未沿用异常值。

M150625 Create(topicId,Trap) 364/364，ev_2d06365f5b080b8137a6863cd6ca6afec93fe10b349f1430d7aae878815f2e1a：默认非空Trap.id查当前主题item、比较原生类型值13，再把主题/物品显示字段及Trap.ts传入视图。M150626 Create(topicId,string,long) 396/396，ev_27e4eee5482bc3f62c805bffb367a8e7b281ff5eaaaa0c9cceb1189008074f53：拒绝空ID、查item和同一类型分支，long参数直接保留。这里只证明默认消费者形状；不从未验证metadata默认枚举值推类型编号，不把ts的复制解释成已恢复全部时间语义。GetCurrTrapId的片段外Hotfix坏指令/全局重叠警告保留，两Create全局重叠警告保留；没有称完整Hotfix或战斗输入已验证。

v2 worker68529 actualexit0/server0。公开close返回cleanup_incomplete（进程argv显示java与预期绝对可执行路径比较不符），不能写公开close成功；随后实际Windows12052/28776缺席，WSL/proc/476缺席，该报告runtime_root所属Java也无，才继续下一目标。工作目录/错误输出均保留，未按进程名批量终止或删文件。首方法45秒观察返回pending，继续同68529，真实65.375秒成功，未重复排队。

证据.cache/rogue-support-tools-20261031/{consumer-evidence-v1.json,actual-six-tool-facts-v1.json,mcp-support-tools-static-v2/findings-0002.json,findings-0003.json,findings-0004.json,completion.json}。183业务文件/201保护输入字节保持，0Android输入/新关/授物/数据库修改；未改源码，不为研究重跑无关测试。

## 主题资料与下一具体方法

浏览器旧变量跨目标恢复失效后仅在既定browser2新建临时页，未改浏览器权限/访问8080。普通长生者宝盒当前DOM确无支援道具，不因此称全站无资料；页面内搜索支援补给站，实际结果定位[本主题猩红珍藏·战术道具箱](https://prts.wiki/w/傀影与猩红孤钻/猩红珍藏#战术道具箱)，修订441594。六项名称/战斗携带量分别与实际导入的usage核同（1/3/1/1/1/2），不采用其他主题轰隆隆/起重机的数量。该具体表没有给出售价，仍缺本主题普通售价出处。第一次domcontentloaded后即时取DOM尚空，保留community-tools-theme-dom-v1.json；实际页面加载后v2取到具体六行。不能将首空结果当没有条目。

仅扫描冻结R-X段对M33727的直接B/BL引用，定位四个调用：M153657领取OnClick、M153660 Render、M153701 CreateTrapViewStruct、M155343商店_GetTipsInfo。direct-trap-callers-v1.json不冒称完整虚/泛型调用图。新工件e765e1dd36f9c0dbf959c5fa744b98b5c2e7e8c656a4623ffc15d370d865d04a/12288字节、27完整种子：OnClick184/184、Render912/912、GetTipsInfo896/896；已取得这三项及同工件内OnConfirmClick240/240的真实REA，未重复前述三项或启动模拟器。

## 替换显示与确认事件证据

M153657 OnClick，ev_082af5cabd8d9856682c9bec7a600073e0b9c4455205315510695c6b2f57332f：当前道具ID为空走OnConfirmClick，已有道具时检查确认开关，已显示则取消。末尾片段外控制流被REA截断，不能把截断当完整实现；独立反汇编实际末尾B目标0x90463b0，冻结索引解析M220372 UISwitchTween.Show。没有为相同字节重新开REA。

M153660 Render，ev_fb5da2d31ab03973f19c24dbfcf71a6ea6610028ef71201a6d0243ed91d15784：默认按主题物品显示名称/图标/用途；当前有道具且不是previewOnly时显示替换部分，文本使用EXCHANGE，否则使用TAKE，并重置确认开关。M155343 _GetTipsInfo，ev_9961cfbcb4d4d5c6111a7ec8980cd7efe42623e18cf0499666b6f1a47126e194：商品类型原生值13且当前道具ID非null时用REPLACE_TRAP_TIP提示。没有据“显示替换”推导商店必须出现同ID商品、重复购买资格或售价。这两函数只有全局重叠警告，Hotfix与实际原生显示仍独立待验。

M153659 OnConfirmClick，ev_139f9ed28bedc47d73fcfbb019f21e4e683542d151c1f9189b485ffefefd93f6：保留片段外Hotfix/尾调用坏指令截断。独立读完整240字节的最后指令，B到0x7c77f5c；冻结generic_functions173016→method_specs190004→UnityEngine.Events.UnityEvent<T>.Invoke M271509，class_inst74实参int。传参是已核RoguelikeRewardItemViewModel.index偏移16；因此这是UI选择index事件，不是直接证明某条领取网络请求。第一次手写十六进制转十进制查询无匹配，改用int(hex,16)并核具体泛型链才采用，未据空结果做规则。下一核真实事件接收者及请求，不把该UI事件当服务器已发物。

新会话14640：首伪码45秒观察pending后同worker59.078秒实际成功，后续三项0.078/0.063/0.016秒；公开close成功，actualexit0/server0，Windows26560/19896现场缺席，工件未变。证据replacement-evidence-v1.json与mcp-replacement-static-v1/findings-0002..0005、completion.json、tail-branches-0x3ec7580.json和tail-branches-0x3ec7638.json。全部7个不同函数及数据/社区来源均只读，183业务文件/201输入保持，0新Android输入/游玩/购买/授物/数据库修改/EXE，不重复不受影响的自动检查。

下一按已定位RoguelikeRewardItemListState.OnClick M153305、RewardSelectState.OnClick M153330、RewardState.OnListClick M153361核事件接收与具体请求，再接独立持有/替换历史和商店/奖励/战斗投影。它们当前仅索引定位，未获函数行为依据；先查既有具体证据再决定是否新REA，避免重复。购买/领取/替换服务、战斗输入与原生效果、本主题正常售价/资格/自然权重仍未完成，完整目标保持。

[PRTS本主题](https://prts.wiki/w/傀影与猩红孤钻#事件节点)的普通首层商店说明包含一个保底支援道具与仅先锋/术师/医疗的招募券范围；特殊深入调查搜索结果有6/8商品位及不同约束，不能移作普通模式商品位数量。商店互动记录页只有对白，不提供商品数量、售价或抽样权重。整页web超时后授权IAB实际DOM已核具体事件节点段，不以超时作缺资料。这里只是社区机制依据，具体版本/物品映射及消费者仍单独核验。

冻结metadata索引只读定位PlayerRoguelikeV2.CurrentData.Trap声明id:string、ts:long，GetCurrTrapId M33727；RoguelikeTrapViewModel.Create M150625/150626为显示消费候选。字段声明不等于完整函数或战斗数量规则。后期视图字段的索引偏移出现16843009xx，不能当有效内存偏移；保留该索引事实，改核实际metadata类型/代码。下一先取这三个具体方法的可解码范围与REA结果，随后核战斗输入及购买/替换合同、实际道具价格/开放。尚未启用自然池、保底抽样或道具发放，不猜权重/战斗数量。


2026-11-01恢复核对：上一目标轮已完成21资格原生/私有恢复并取得三新方法静态完整性，属于实际进展。REA初会话48759跨恢复后句柄不存在，Windows34588/3224及相关进程现场缺席；completion记初始化53.734秒、工具列表0.422秒后无open/pseudo，空闲到2026-10-31T10:50:38Z退出0，工件未变。保留mcp-support-tools-static-v1，新v2只复用同工件分析尚未取得的三方法，不重启模拟器或重复已取得证据。静态工件ccbb97bc/12288字节、29完整种子；M150625 364/364、M150626 396/396、M33727 192/192。
