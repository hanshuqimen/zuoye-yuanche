"""Server-priced native voucher/orundum payments; a declaration is never a price."""

from terralocal.server.domain.errors import DomainError, NotImplementedFeature


def charge(ctx, count: int, mode: int, *, classic: bool, price: int,
           item_id: str | None = None, items: list | None = None) -> None:
    if type(mode) is not int or count not in {1, 10}:
        raise DomainError("INVALID_GACHA_PAYMENT", "寻访次数或支付类型无效")
    if item_id:
        raise NotImplementedFeature("本期卡池的专用寻访物品")
    if mode == 9:
        if count != 10 or not items or len(items) > 5:
            raise DomainError("INVALID_GACHA_PAYMENT", "组合支付需要十连及有效明细")
        # The frozen client sends Combine even when the entire ten-pull is
        # paid with one ten-pull voucher. Its count is one item, worth ten draws.
        allowed = {"7003": (1, 1, "TKT_GACHA"), "4003": (price, 1, "DIAMOND_SHD"),
                   "7004": (1, 10, "TKT_GACHA_10")}
        if classic:
            allowed["classic_gacha"] = (1, 1, "CLASSIC_TKT_GACHA")
            allowed["classic_gacha_10"] = (1, 10, "CLASSIC_TKT_GACHA_10")
        cost, units = [], 0
        seen = set()
        for entry in items:
            item, quantity = entry.get("id"), entry.get("count")
            if (item not in allowed or item in seen or type(quantity) is not int or quantity <= 0):
                raise DomainError("INVALID_GACHA_PAYMENT", "组合支付包含非法或重复项目")
            multiplier, draws, kind = allowed[item]
            if quantity % multiplier or ctx.data.item(item)["itemType"] != kind:
                raise DomainError("INVALID_GACHA_PAYMENT", "支付数量或币种与寻访价格不符")
            units += quantity // multiplier * draws
            cost.append({"id": item, "count": quantity})
            seen.add(item)
        if units != count:
            raise DomainError("INVALID_GACHA_PAYMENT", "组合支付不能覆盖本次十连")
    else:
        if items:
            raise DomainError("INVALID_GACHA_PAYMENT", "此支付方式不能包含组合明细")
        modes = {0: ("4003", price * count, "DIAMOND_SHD")}
        if count == 1:
            modes[1] = ("7003", 1, "TKT_GACHA")
            if classic:
                modes[6] = ("classic_gacha", 1, "CLASSIC_TKT_GACHA")
        else:
            modes[2] = ("7004", 1, "TKT_GACHA_10")
            modes[5] = ("7003", 10, "TKT_GACHA")
            if classic:
                modes[7] = ("classic_gacha_10", 1, "CLASSIC_TKT_GACHA_10")
                modes[8] = ("classic_gacha", 10, "CLASSIC_TKT_GACHA")
        if mode not in modes:
            raise DomainError("INVALID_GACHA_PAYMENT", "此卡池不能使用所选支付方式")
        item, quantity, kind = modes[mode]
        if ctx.data.item(item)["itemType"] != kind:
            raise DomainError("GAMEDATA_INVALID", "寻访支付物品类型不匹配", 503)
        cost = [{"id": item, "count": quantity}]
    ctx.consume(cost)
