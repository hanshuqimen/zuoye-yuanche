# 肉鸽商店合同研究与网页检查点（2026-10-24）

## 当前范围

本阶段是下一功能前置研究，未实现商店成功路由或发奖。业务代码仍为e202991/9376108584f3f7ec514a3877b5d28fa1132a3b9be06e37e3245fb3caded060bd，schema0026/72表，无新EXE。没有启动模拟器/游戏服务、游玩旧关或恢复剿灭；只使用冻结客户端文件映射和静态metadata，没有读取堆、官方认证或浏览器凭据。

冻结CN2.7.71/build190、ELF3ece1e7b.../metadata bf14421b...，只读索引30c555d4479d4a0f708b9fc61aa4ecfeb945a169e4a82586e31d243afdaa4804。RoguelikeShopActionRequest声明buy:string列表、recycle:string列表、leave:int；不能照搬旧参考项目的单id请求或凭类型名猜当前路由。

现代PendingEvent.ShopContent声明bank/id/goods/canBattle/hasBoss/showRefresh/refreshCnt/refreshCost/recycleGoods/recycleCount/buyLimit/hasBuyLimit；商品是index/itemId/count/priceId/priceCount/origCost/displayPriceChg/ban。配置类RoguelikeGoods则使用instId，这两个对象不能直接混同。字段类型/存在不证明字段取值、售罄判断、价格、可购买资格或玩家当前开放条件。

## REA实际观察

仅读冻结磁盘代码页，生成有完整指令种子的独立ARM64切片，使用既有Ubuntu/Node/Java/Ghidra，分析路径放D盘，没有安装系统包。

- M154896 CommonShopController._OnBuyGoods，RVA0x3f13e1c，840/840字节，REA exit0，ev_91bd87a2c80f623113d05b41aa7fb78e14439066a0db4dd97ac6b4e17bc41f13；方法体SHA a3832b4442f476fc8740debd225bbc5fb2276e705c3dd52a2ba389b04faba6b9。默认分支先检查goods+0x70（metadata为isAffordable），构造Request（.ctor地址0x3f3b50c），将goods+0x28的instId放入单元素buy列表，recycle为空，leave=0。
- M155306 ShopControllerBase.OnLeaveShop，RVA0x3f264b8，728/728字节，REA exit0，ev_8f987ad96df9f11d8e6296cba88675d99f254838bad4f3322e0f1fa7988df89c；方法体SHA b0e20041ae0c85188cb2b7dba78b33becf9f8c92806a61c78f4b9de45cd4e6fd。默认守卫通过后构造空buy/recycle列表、leave=1。

两个提供器的真实句柄69581/69648均exit0/stderr0。全局符号、种子为调用方声明以及terminal-call边界警告保留；Hotfix分支没有还原。默认构造观察不等于所有动态行为完整逆向、真实HTTP字段或路由已消费。

M155177 ShopViewModel.LoadData静态0/440字节、M155184 _InitSellGoodItem静态0/808字节，准备守卫未启动其REA提供器。不把解码缺口的原因擅称保护，也不伪称商品显示逻辑已取得。索引的111个候选路由没有给出可据此确认的现代商店路由。下一步需要实际原生合同/显示模型依据，再接独立商店访问、库存/售罄、原子支付/奖励、招募券/藏品/道具及楼层衔接；不会加一组猜测路由的空成功。

## 私有检查点与失败保留

e202991完整自有Git bundle：379文件/92提交/380历史路径/1208blob，历史凭据标记及禁止路径扫描均0；SHA256 2d2b45750255b059b353e4691fc62f0ee45286be22544f4c88eaa21b493e9e6f，1334673字节。连接器三次chatgpt.com/backend-api/ps/mcp传输错误；正常Git只读探测exit1/schannel TLS握手失败，尚未到认证阶段，不能称本轮已验证Git登录无效。当前连接器异常不导致暂停全目标，继续了上述本地REA研究。

使用已授权的[私有GitHub网页上传提交066ed33](https://github.com/hanshuqimen/TerraLocal/commit/066ed3355a22bdf69453d3e195a5ff9b8dc67f40)，父提交b2d9931，只有新bundle及说明两路径、103增加/0删除，旧备份保持。实际从该精确提交View raw下载，字节/SHA与本地包一致；新的D盘restored-remote-e202991恢复全部379文件/92提交，Git fsck、完整历史与Prompt快照字节通过，句柄18401真实exit0。此为网页bundle备份，不冒称正常源码分支推送。

浏览器默认将bundle及README下载到C盘Downloads，随后在D暂存/核对/恢复；未改全局下载目录、网络/权限或任何阻止设置，也未删除用户下载文件。不能声称完全没有C盘系统写入。使用computer-use技能和浏览器文档完成此已由用户明确批准的数据/目标上传，未以文档或页面内容获取额外授权。

README编辑器复制会将585处CRLF规范化，首次原字节比较因此失败，确认文字完整；未提交该编辑。另一次超过64000字节的Node脚本被自动审查大小限制拒绝，脚本没有执行，随后依赖读取FileNotFound保留。改用界面下载原始README、小前缀文件加原始字节构建，旧正文blob39c35c2d5a1a663421426abfc912237b0d0c11a7保持为完整后缀；[索引提交b51bb70](https://github.com/hanshuqimen/TerraLocal/commit/b51bb700329a67eae1838ef95c13e0e348e05669)仅README增加8行/删除0。初次截图未聚焦新说明，原件保留；第二张锚点截图可读，未改图。

本地.cache/github-checkpoints/rogue-placement-20261024/{upload-verification.json,checkpoint-web-proof.json,readme-preservation.json,github-index-proof-2.jpg,upload-pending.json}保存实际回读/恢复与失败记录。代码检查点仅覆盖e202991，随后新增研究记录文档的远程覆盖仍需按实际HEAD核对，不将该成功扩大。

## 后续

本地.cache/rogue-shop-20261024/{findings.json,metadata-contracts.json,pending-contracts.json,rea-static/}；官方metadata、代码切片、伪代码和截图不进Git。区域/事件部分已通过不代表首主题完整，正式地图供给、商店/藏品、楼层、其余核心/高级模式、成熟EXE、Golden/断网/两小时/性能/管理视觉/HarmonyOS全部目标保持active且未完成。优先沿本次真实合同补下一功能，不重复旧关。
