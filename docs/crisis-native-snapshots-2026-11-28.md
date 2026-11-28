# 原版危机合约成绩快照合同（2026-11-28）

源码搜索确认当前尚无crisisV2/getSnapshot路由，只有独立的local/v1/crisis-v2/history；后者不是原版成绩快照接口。本轮取得真实请求绑定、字段别名及六个消费者，尚未新增该路由或声称快照已经可用。随后发现并修复[零分首通纪录缺陷](crisis-zero-records-2026-11-28.md)，完整接口仍须继续实现。

## 原版绑定及字段

冻结2.7.71 ELF/metadata沿用已锁指纹，六个类型已在当前NativeTypes CLI中实际匹配，命名属性另外从原始表核验。M162590默认请求的0xc05beb0经单元0xc60e8d8/编码0xa000cf9d对应字面量26574 **crisisV2/getSnapshot**。0xc067db8对应CrisisV2GetSnapshotRequest，0xc16b4c0对应MsgBundle<Request>，MethodSpec289724对应UISender.SendRequest<CrisisV2GetSnapshotResponse>，0xc001110绑定M162591 _OnGetSnapshotProceed。请求类型无自有字段，继承部分仍按共同协议处理，不把候选字符串当作绑定证明。

七个实际JsonProperty名称如下；构造275696、PropertyName ordinal5及setter275695均验证，current/nst两个既有字段作正对照：

| 声明字段 | 线上名称 |
| --- | --- |
| GetSnapshotResponse.simpleData | simple |
| GetSnapshotResponse.detailData | detail |
| SnapShotBase.oldCommentIdList | CommentOld |
| SnapShotBase.newCommentIdList | CommentNew |
| SnapShotBase.runeIdList | rune |
| SimpleSnapshot.squadCharList | squad |
| SnapshotSquadChar.currTmplId | tmplId |

其他声明包括共同scoreCurrent/ts，简略的assistSkinId及charId，详情的leftHp/scoreRecord/squad/assistFriend；SharedCharData的完整序列化和历史捕获仍需独立完成。不能用当前干员养成值覆盖当时的战斗状态，或为缺失leftHp填写假0。

## 六处REA与边界

M162590请求704、162591回调380、162588 GetCacheData148、162589 CheckIfDataValid136、162767详情读取820、162768简略读取1340，共六个不同函数3528字节；三页20,480字节容器SHA-256 `ea606371c471e3f317ae975f193fefdd8b82839ff1d31cb43263ca431446f1e6`。20961实际退出0，public status/close、主体SHA、入口和输入保持已核。

回调把响应两张字典写入CrisisV2SnapshotData，并把当时玩家newRecordTs写入wrapper.lastTs。详情读取使用leftHp、SharedCharData队伍和助战；简略读取显式处理空槽和空模板，并在显示参数中使用-1表示没有血量详情。缓存自定义有效性、父页面的字典键/回退规则、共同差异字段读取，以及SharedCharData投影还需要继续核对，未把这六个方法当成全调用链。

证据在`.cache/crisis-20261128/native-snapshot-contract-v1/`的metadata、native-wire-types、native-wire-attributes、wire-alias-bindings和default-request-binding；`rea-native-snapshot-20261128-v1/static-methods.json`及`mcp-native-snapshot-20261128-v1/analysis-summary.json`保存限定输入与结果核验。首次CLI后处理误用unmatched_filters键，在写输出前失败；核实实际unmatched_type_filters后重试并保存，错误保持。原始客户端数据、私有工具结果与保存不公开，只发布自有源码、结论和索引。
