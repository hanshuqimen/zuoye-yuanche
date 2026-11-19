"""IS2 base NORMAL/0 scoring adapter.

The seven weights are the documented PRTS player rules, not an extracted
official server formula. Versioned policy; multipliers, caps and conversion
ratios must come from the imported table. No inference for other themes.
https://prts.wiki/w/傀影与猩红孤钻
"""

from math import isfinite

from terralocal.server.gamedata.repository import fingerprint

POLICY = "rogue1-normal0-prts-score-v1"
WEIGHTS = (1, 10, 20, 30, 5, 2)
FLOORS = (0, 30, 80, 150, 270, 400, 550)


class FirstThemeScore:
    def __init__(self, data):
        table = data.table("roguelike_topic_table")
        detail = table["details"]["rogue_1"]
        const, dc = table["constant"], detail["detailConst"]
        matches = [d for d in detail["difficulties"]
                   if d["modeDifficulty"] == "NORMAL" and d["grade"] == 0]
        if len(matches) != 1:
            raise ValueError("首主题结算缺少唯一NORMAL/0难度")
        self.difficulty = matches[0]
        factor = self.difficulty.get("scoreFactor")
        if (type(factor) not in (int, float) or not isfinite(factor) or factor != 1
                or self.difficulty.get("bpValue") != 0 or const.get("milestoneTokenRatio") != 1
                or const.get("outerBuffTokenRatio") != 10
                or dc.get("historicalRecordsMode") != "NONE"
                or dc.get("historicalRecordsCount") != 0 or detail["gameConst"].get("gpScoreRatio") != 0):
            raise ValueError("首主题基础评分倍率、历史或代币政策不匹配")
        self.grow_cap = dc.get("outerBuffTokenSum")
        if type(self.grow_cap) is not int or not 0 < self.grow_cap < 2**31:
            raise ValueError("首主题灵感上限非法")
        self.updates = detail["milestoneUpdates"]
        previous = None
        for i, row in enumerate(self.updates):
            start, end = row.get("updateTime"), row.get("endTime")
            if (type(start) is not int or type(end) is not int or end != -1 and end <= start
                    or previous is not None and start != previous
                    or end == -1 and i != len(self.updates) - 1
                    or type(row.get("maxBpCount")) is not int or not 0 < row["maxBpCount"] < 2**31):
                raise ValueError("首主题笔记更新窗口非法")
            previous = end
        if not self.updates or previous != -1:
            raise ValueError("首主题笔记更新窗口不完整")
        self.hash = fingerprint({"policy": POLICY, "data": data.manifest["hash"],
            "difficulty": self.difficulty, "updates": self.updates, "grow_cap": self.grow_cap,
            "weights": WEIGHTS, "floors": FLOORS, "bp_ratio": 1, "grow_ratio": 10})

    def calculate(self, counts, before, at):
        if (type(counts) is not list or len(counts) != 7
                or any(type(n) is not int or not 0 <= n <= 10000 for n in counts)
                or counts[0] not in range(len(FLOORS))):
            raise ValueError("探索评分统计超出已接纳范围")
        # Native score-view order: floors, nodes, normal, elite, boss, items, recruits.
        detail = [[counts[0], FLOORS[counts[0]]], *[
            [n, n * weight] for n, weight in zip(counts[1:], WEIGHTS, strict=True)]]
        score = sum(row[1] for row in detail)
        windows = [r for r in self.updates if r["updateTime"] <= at and (r["endTime"] == -1 or at < r["endTime"])]
        if len(windows) != 1:
            raise ValueError("结算时间没有匹配的笔记上限")
        bp, grow = before["bp"], before["grow"]
        if any(type(n) is not int or not 0 <= n < 2**31 for n in (bp, grow)) or grow > self.grow_cap:
            raise ValueError("探索外部余额非法")
        # A historical cap never removes previously earned candles.
        gained = min(score, max(0, windows[0]["maxBpCount"] - bp))
        gp = min(self.grow_cap - grow, (bp + gained) // 10 - bp // 10)
        return detail, score, gained, gp
