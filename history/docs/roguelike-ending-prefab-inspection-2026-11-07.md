# 结束页工具配置的只读资源核查

本轮继续核对工具结果页，0游戏输入、0新战斗、0生产源码/数据库/官方资源修改。完整交付目标未完成；此前主动放弃6分原生代表不重测。QA23确认已收到，但现有原生记录没有新协议弹窗或接受动作，不能补造接受操作。

## 实际结果

冻结基础APK的SHA256仍为`0b79b85383e21a6343283bc6bfd7a9d24eb4134abf901115f757da6a5d50f6db`。包内`assets/AB/Android/ui/roguelike.ab`为1264869字节，SHA256 `a9ec7a2fa32874855d8a762fe665b9b92fe177138ac328dbb3ecb3436a41106f`。已有自有LZ4AK解码器只在解析上下文使用，不改包。此包8982对象、2731个MonoBehaviour、242种内嵌类型；本地容器有15个名称包含ending的入口（其中一项是pending，不称15种结束页）。

仅按内嵌类型结构筛选，未发现`_showTrap`，不是把它读成false。两个目标prefab的有界层级遍历共25对象、7组件，也未找到该字段。另检查基础APK的`[uc]roguelikeentry.ab`（361对象）及当前缓存版本26-09-22-07-47-20_6c71fa的rogue_cmnart1/2、rglktp_rogue_1add/rogue_5（303/172/351/357对象），均无该字段；缓存包不能冒称与基础APK同版本。

通过只读元数据索引确认，此前REA M151846/151848属于`Torappu.UI.Roguelike.RoguelikeClassicEndingStatsRelicGroupView`。它的默认过滤逻辑仍是已有证据，但当前实际页面实例、prefab绑定及Hotfix覆盖尚未核定；不能从类名或有限包内缺字段推断当前页面实际调用、工具必被隐藏、工具工厂正确或客户端缺陷已修复。其余同名字段属于菜单组件，也不能替代当前结束页。

两种结束页根组件已读出本地_rootView/_container引用；脚本引用为外部CAB，已保留引用清单，但没有自动加载外部依赖。下一可从精确CAB/实际页面绑定继续定位，不重新扫描整个项目或重打关卡。当前不修改客户端过滤，也不增加服务端万能字段。

## 失败与修正

v1无进度输出探测曾达1166925824字节工作集/152.34375 CPU秒，已只停止经父PID和命令行验证的自有只读进程9488；恢复核对9488/18364均无该进程，旧41366句柄已丢失，退出码未知。原先停止理由写“全MonoBehaviour扫描”，后续阶段证据纠正：卡点实际在扫描之前的`env.container`。

v2逐阶段输出显示加载及对象目录在3.313秒完成，随后停在Environment.container；读取已安装UnityPy源码确认该属性先调用_build_container_index→parse_preload_table→外部指针解析。为避免自动依赖遍历，核验33368/父26464的身份后明确停止，10821实际exit1；不是观察超时后另开重复worker。停止记录保留。

v3改用每个本地SerializedFile的container，不调用Environment.container，也不解引用外部指针，1.985秒完成/实际exit0。v4把ComponentPair误作PPtr，actualexit1；核对已安装类型的component字段后另存v5，2.047秒完成/exit0。v6内嵌类型筛选、v7五个其他包、v8精确根引用分别实际exit0。保留旧失败脚本，不覆盖失败。v3被后续定点脚本复用，其目录结果可重生成，不把重用算成新增验证用例数量。

## 证据与范围

本地`.cache/rogue-ending-tool-prefab-20261107/`保留v1/v2-controlled-stop.json、catalog-v3.json、ending-v5.json、configs-v6.json、other-bundles-v7.json、ending-refs-v8.json及对应自有探测脚本。官方对象/类型字段和原始输出仅本地，不收录Git。没有新增联网查询、依赖安装、模拟器或REA进程；没有重跑未受影响的129检查，没有新EXE。

生产业务仍85a020af/187 Python、schema0036/77；最新已验证私有检查点仍456e1c2（源06a0e79），此前完整恢复证明保持。本次是资源定位与证据边界修正，不称游戏功能新增或结束页图标验收通过。完整主要系统、自然供给与正式成熟交付继续未完成。

## 继续核查：冻结主题包的默认配置已读出

上一轮属于进展：有实际受控停止与局部资源负结果，缩小了下一步；不是仅重述状态。本轮Git从179018f干净恢复，不启动模拟器或重打任何关卡。

纠正资源范围：APK内置hot_update_list为26-08-16-13-31-15_02805c，实际冻结资源清单为26-09-22-07-47-20_6c71fa；ui/roguelike.ab两份清单的MD5相同，但后者另列ui/rglktopic/rogue_1.ab及rogue_1_update.ab，APK并不包含这两个主题包。前次基础包负结果不能替代实际主题UI配置。只读库存旧记录也明确列了主题包5366371字节及更新2826216字节；本轮没有把尺寸记录当成当前模拟器MD5证明。

按既有冻结CDN和精确两项清单下载至新D本地证据目录frozen-theme-ui-v18，不写运行资源目录/旧receipt，不更新APK或存档。清单SHA256 d1ac02a61d98e6e4c772335bb85dc44da4794a0a8bc915354b6f9ffbc7ec1f35。两ZIP下载大小4925967/2597975，解压成员5366371/2826216；verify_archive逐项验证名称、大小和清单MD5 ad5dc1e523cd52afa51fd8b84cfccdea / 4bf4899944a1e1eb2d64b33d5869e294。成员SHA256分别30bbe9b6d8c1c2adec822330a33769d13b0b83be336c271ba19c06e5d632995b / cd61d42d8e4e2b725128072ef6a5121b9af34ad0dfa209d754f50ff501542ef7。仅这两次公开资源请求，无登录、认证或支付。

实际主题包11128对象、193唯一本地路径，更新包190对象。主包找到4个_showTrap，均为0；其中明确的ending/stats/rogue_ending_stats_relic_view.prefab，字段类型为内嵌树的UInt8，值0。已逐条核对ending_view的_pageViewPrefabs[0]→panel_stats_items组件，再由_viewComponentPrefabs[2]→该收藏品组件，均为本地PPtr，不靠外部依赖猜绑定。此配置结合此前REA showTrap反码bit8过滤，支持本冻结主题默认收藏品分组排除工具；因此不为服务端activeToolList非空而强制前页加图标或数量。获得物品计分与这个分组计数独立，已有6分代表保持。

**已完成的是冻结prefab配置及引用链证据，不是当前运行内存/Hotfix状态证明。** 不宣称工具工厂、所有主题或所有运行覆盖已核。本轮无新原生输入、服务进程、战斗或新EXE，前页没有新增图标显示通过声明。无需为这项默认配置再重播结果或旧关。

## 目录定位与REA边界

v13只解析2529个UnityFS包目录，0.750秒、0资产载荷加载。发现同名CAB-658d74…同时在两个不同匿名包，v14用对象ID才在933172…包解析到旧结束页脚本；25ca9f…只13对象，不能“取第一个CAB匹配”。此后基础包94匿名载荷及29内置序列化组的有界只读定位均未找到目标组件；globalgamemanagers.assets找到目标MonoScript13319，但其余28组无该脚本引用，不能从注册了类推出已使用该prefab。这些负结果保留，不再反复扫描基础包。

新REA工件83bef1e5c12d928dafda1cc2e0867b72ed7fbf67490edf79dcac033cc6cf7268，12288字节/35完整种子。M151971加载380/380，ev_c27944e63a7fd73eb2a118ba32863c1f945650ad009c46145f35b3d4873ecc7c，默认调用ResourceUrls.GetRoguelikeTopicEndingPath；M151851构造144/144，ev_e43bb5550eb79bb41a88999707a9e3d3ee1c32f607cddc1b1749cc936bec1f47。两者均保留坏指令/Hotfix截断和全局重叠警告，不据构造函数未写字段便认定运行值为false。首次45秒观察返回pending，原REA同worker于51.094秒完成，未重排；随后0.015秒。close4成功/server0/19095actualexit0，11832/13004现场缺席。原始代码/目录/资源仍仅本地。

v19首次按Python bool强断言失败，实际内嵌类型是UInt8、UnityPy返回int；v20保留原值和类型，只接纳真实0/1，两个包解析actualexit0。v21引用链与v22完整冻结校验均actualexit0。旧v19脚本及失败事实保留，不当作客户端故障。

## 源码修复与验证

现有tools/research/unpack_client_lua.py的报告阶段也调用Environment.container，会触发已复现的全局依赖预加载。新增local_container_paths，只读已加载、非依赖SerializedFile的本地目录，去重并排序；不改变Lua验签、解密、输出文件或游戏服务器业务。

新增两个使用真实UnityPy类型的合成回归检查：外部preload一旦解析就主动失败，证明旧API确实触发、修复目录读取不触发；多文件重复路径稳定合并且不纳入依赖资产。所在模块6检查（2新+4受影响既有）全部通过，2文件Ruff和diff检查通过；保留既有Starlette弃用警告。不把这6项等同原生或累加为129游戏检查，也未重复无关检查。

真实冻结主题的v22用新helper读193路径，全局依赖索引始终false，并再核ZIP清单MD5、主题包SHA与三段引用/_showTrap=0。证据frozen-default-verification-v22.json、ending-style-links-v21.json、theme-configs-v20.json、frozen-theme-ui-v18/receipt.json、lua-catalog-regression-v1.xml；REA目录.cache/rogue-ending-controller-20261107。工具/测试为自有源码，原始资源/图片/脚本/日志仅.cache，不入Git。

生产业务仍85a/187、schema0036/77；新工具修复尚在本地，最新已验证远程仍456e1c2，不冒称新源已在旧包。结束页默认配置问题在上述范围收尾；下一转首主题事件节点的现有协议/事务驱动与匹配数据覆盖审计，从rogue_visits.py和rogue_events.py定位未接效果，不把未知自然池补为默认随机发放。完整目标保持ACTIVE。
