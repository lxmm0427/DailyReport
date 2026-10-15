"""统计、重点事件遴选、跨日主线追踪与各章节文字生成。

正文中的事实全部来自已核验事件表；分析性语句统一以“分析认为/综合看/研判”等措辞标出，
与已核实事实区分。
"""
from __future__ import annotations

import re
from collections import Counter, OrderedDict
from dataclasses import dataclass

from .events import Event, parse_day

# ---------------------------------------------------------------- 平台重要度
_IMPORTANCE = [
    ("航空母舰", 10), ("两栖攻击舰", 8), ("直升机母舰", 8), ("攻击核潜艇", 7), ("战略轰炸机", 9),
    ("弹道导弹侦察机", 8), ("电子侦察机", 8), ("高空侦察", 7), ("电子攻击机", 6), ("预警", 6), ("无人机", 6),
    ("导弹巡洋舰", 6), ("导弹驱逐舰", 5), ("船坞", 5), ("常规潜艇", 5), ("电子战飞机", 5), ("反潜巡逻机", 5),
    ("海上巡逻机", 4), ("导弹护卫舰", 4), ("加油", 4), ("综合补给舰", 3), ("战斗机", 3),
]


def importance(e: Event) -> float:
    base = next((w for k, w in _IMPORTANCE if k in e.platform), 2)
    return base + (1.5 if e.country == "美国" else 0) + 0.5 * (e.count - 1) + (1 if e.formation else 0)


# ---------------------------------------------------------------- 工具
def cn_date(day: str, year: bool = False) -> str:
    d = parse_day(day)
    return f"{d.year}年{d.month}月{d.day}日" if year else f"{d.month}月{d.day}日"


def hm(hhmm: str) -> str:
    return f"{int(hhmm[:2])}时{hhmm[2:]}分"


def time_span(e: Event) -> str:
    return f"{hm(e.start)}至{hm(e.end)}"


def core(events: list[Event]) -> list[Event]:
    return [e for e in events if e.direction in ("东海", "南海", "黄海")]


def join_cn(items: list[str]) -> str:
    items = list(OrderedDict.fromkeys(items))
    if len(items) <= 1:
        return "".join(items)
    return "、".join(items[:-1]) + "和" + items[-1]


REL_VERB = {"进入": "进入", "离开": "离开", "活动": "在"}


def action_phrase(e: Event) -> str:
    """如“进入东海”/“离开南海”/“在东海活动”。"""
    if e.relation == "活动":
        return f"在{e.region}活动"
    return f"{e.relation}{e.region}"


# ---------------------------------------------------------------- 统计
@dataclass
class DayStats:
    air_batches: int
    air_sorties: int
    ships: int


def foreign_stats(events: list[Event]) -> DayStats:
    ev = [e for e in core(events) if e.foreign]
    air = [e for e in ev if e.kind == "air"]
    return DayStats(len(air), sum(e.count for e in air), sum(e.count for e in ev if e.kind == "ship"))


def hourly_counts(events: list[Event]) -> tuple[list[int], list[int]]:
    """每小时 h:30 时刻在位的飞机架次/舰艇艘次（与官方样例口径一致，含中方）。"""
    air, ship = [0] * 24, [0] * 24
    for e in core(events):
        s, t = e.minutes()
        for h in range(24):
            if s <= h * 60 + 30 <= t:
                (air if e.kind == "air" else ship)[h] += e.count
    return air, ship


def _delta(word: str, diff: int, unit: str) -> str:
    if diff > 0:
        return f"{word}增加{diff}{unit}"
    if diff < 0:
        return f"{word}减少{-diff}{unit}"
    return f"{word}持平"


def overview(day: str, events: list[Event], prev: list[Event] | None) -> str:
    st = foreign_stats(events)
    s = (f"{cn_date(day)}，共掌握外（台）各型飞机{st.air_batches}批{st.air_sorties}架次、"
         f"舰船{st.ships}艘位当面活动")
    if prev is not None:
        p = foreign_stats(prev)
        s += f"，与1日前相比，{_delta('飞机', st.air_sorties - p.air_sorties, '架次')}、{_delta('舰船', st.ships - p.ships, '艘')}"
    tasks = Counter(e.task for e in core(events) if e.foreign)
    dirs = Counter(e.direction for e in core(events) if e.foreign)
    if dirs:
        s += "。活动主要分布于" + "、".join(f"{d}方向（{n}批/艘）" for d, n in dirs.most_common())
    if tasks:
        s += "，任务以" + "、".join(t for t, _ in tasks.most_common(3)) + "为主"
    return s + "。"


# ---------------------------------------------------------------- 一、重要军事动向
def group_formations(events: list[Event]) -> list[list[Event]]:
    """把同一编队的多个批号归为一组，其余各自成组。"""
    groups, seen = [], set()
    for e in events:
        if e.batch in seen:
            continue
        if e.formation:
            g = [x for x in events if x.batch in e.formation]
            seen.update(x.batch for x in g)
            groups.append(g)
        else:
            seen.add(e.batch)
            groups.append([e])
    return groups


def lead(g: list[Event]) -> Event:
    lp = g[0].formation_lead
    return next((e for e in g if e.platform == lp), g[0])


def important_groups(events: list[Event], k: int = 4) -> list[list[Event]]:
    gs = group_formations([e for e in core(events) if e.foreign])
    gs.sort(key=lambda g: (-max(importance(e) for e in g) - 0.5 * (len(g) - 1), lead(g).start))
    return gs[:k]


def order_group(g: list[Event]) -> list[Event]:
    order = g[0].formation_order or []
    return sorted(g, key=lambda x: order.index(x.platform) if x.platform in order else len(order))


def describe_group(g: list[Event]) -> str:
    g = order_group(g)
    e = lead(g)
    names = join_cn([x.platform for x in g])
    n = sum(x.count for x in g)
    qty = f"（{len(g)}批{n}架次）" if e.kind == "air" and len(g) > 1 else (
        f"（1批{n}架次）" if e.kind == "air" else (f"共{n}艘" if len(g) > 1 else ""))
    src = "、".join(s for s in e.sources)
    return (f"{e.country}{names}{qty}{action_phrase(e)}，执行{e.task}，时间为{time_span(e)}"
            f"（经{src}交叉核验）。")


def section_important(events: list[Event]) -> list[str]:
    out = []
    for i, g in enumerate(important_groups(events)):
        e = lead(g)
        out.append(f"（{cn_num(i + 1)}）{e.country}{e.platform}在{e.region}开展{e.task}。{describe_group(g)}")
    if not out:
        out.append("当日未掌握外（台）重要机舰在东海、南海、黄海方向的可信活动。")
    return out


# ---------------------------------------------------------------- 三、外（台）机舰活动情况
def country_order(events: list[Event]) -> list[str]:
    tot = Counter()
    first = {}
    for i, e in enumerate(core(events)):
        if e.foreign:
            tot[e.country] += e.count
            first.setdefault(e.country, i)
    return sorted(tot, key=lambda c: (-tot[c], first[c]))


def cn_num(n: int) -> str:
    d = "零一二三四五六七八九"
    if n <= 10:
        return "十" if n == 10 else d[n]
    if n < 20:
        return "十" + d[n - 10]
    return d[n // 10] + "十" + (d[n % 10] if n % 10 else "")


def section_countries(events: list[Event]) -> list[tuple[str, str]]:
    out = []
    ev = core(events)
    for i, c in enumerate(country_order(events)):
        air = [e for e in ev if e.country == c and e.kind == "air"]
        ship = [e for e in ev if e.country == c and e.kind == "ship"]
        parts = []
        if air:
            items = "；".join(f"{e.platform}（1批{e.count}架次）赴{e.region}执行{e.task}" for e in air)
            parts.append(f"飞机{len(air)}批{sum(e.count for e in air)}架。{items}。")
        if ship:
            items = "；".join(f"{e.platform}在{e.region}执行{e.task}" for e in ship)
            parts.append(f"舰船{sum(e.count for e in ship)}艘。{items}。")
        out.append((f"（{cn_num(i + 1)}）{c}", "".join(parts)))
    return out


# ---------------------------------------------------------------- 四、美重要武器平台
def section_us(events: list[Event]) -> str:
    us = [e for e in core(events) if e.country == "美国"]
    if not us:
        return "当日未掌握美军重要武器平台在东海、南海、黄海方向的可信活动。"
    us.sort(key=lambda e: -importance(e))
    regions = join_cn(sorted({e.region for e in us}, key=lambda r: [x.region for x in us].index(r)))
    seen, picked = set(), []
    for e in us:
        k = (e.platform, e.region, e.task)
        if k not in seen:
            seen.add(k)
            picked.append(e)
    items = "；".join(f"{e.platform}在{e.region}执行{e.task}" + (f"（{e.count}架次）" if e.kind == "air" else "")
                     for e in picked[:6])
    kinds = {e.kind for e in us}
    mode = "海空一体" if len(kinds) == 2 else ("以海上编队为主" if "ship" in kinds else "以空中侦巡为主")
    tasks = join_cn([e.task for e in us][:3])
    return (f"当日，美军在{regions}活动的重要武器平台主要包括{items}。"
            f"综合看，美军{mode}维持前沿存在，当日任务集中于{tasks}等方面（分析性判断）。")


# ---------------------------------------------------------------- 五、次日关注重点
def section_next(events: list[Event], focus_title: str | None) -> str:
    nums = "一二三四五"
    items = []
    for g in important_groups(events, 3):
        e = lead(g)
        q = f"（{len(g)}批{sum(x.count for x in g)}架次）" if e.kind == "air" else (f"等{len(g)}艘" if len(g) > 1 else "")
        verb = "离开后是否回返" if e.relation == "离开" else "后续动向"
        items.append(f"持续跟踪{e.country}{e.platform}{q}{verb}及在{e.direction}方向的{e.task}延续情况")
    if focus_title and len(items) < 3:
        items.append(f"关注{focus_title}的阶段演变")
    if not items:
        return "持续关注外（台）机舰在东海、南海、黄海方向的活动变化。"
    return "".join(f"{nums[i]}是{t}。" for i, t in enumerate(items))


# ---------------------------------------------------------------- 二、重点态势分析（跨日主线）
# Public compatibility exports; facts and comparisons live in focus.py.
from .focus import (Thread, find_threads, focus_analysis, section_focus,
                    _phase_split, _day_relation, _gaps, _trend_word)  # noqa: E402,F401


# ---------------------------------------------------------------- 附件表
def naval_table(events: list[Event]) -> list[list[str]]:
    rows = OrderedDict()
    for e in core(events):
        if e.kind != "ship":
            continue
        rows.setdefault((e.country, e.base), []).append(e)
    out = []
    for (c, b), es in sorted(rows.items(), key=lambda kv: (kv[0][0] != "中国",)):
        es.sort(key=lambda e: e.start)
        f = es[0]
        notes = list(OrderedDict.fromkeys(_remark(e, ship=True) for e in es))
        out.append([c, b, "、".join(OrderedDict.fromkeys(e.platform for e in es)),
                    f"{f.start}-{f.end}在{f.region}执行{f.task}；最近距我领海线—公里",
                    "航迹监测、开源情报综合分析", "；".join(notes)])
    return out


def air_table(events: list[Event]) -> list[list[str]]:
    rows = OrderedDict()
    for e in sorted(core(events), key=lambda e: e.start):
        if e.kind == "air":
            rows.setdefault((e.country, e.base, e.platform), e)
    out = []
    for (c, b, p), e in sorted(rows.items(), key=lambda kv: kv[0][0] != "中国"):
        out.append([c, b, p, str(e.count), str(e.count), f"{e.region}前沿机位",
                    f"{int(e.start)}-{int(e.end)}执行{e.task}，活动于{e.region}", "—"])
    return out


# ---------------------------------------------------------------- 明细表字段
_CN_PREFIX = [("空警-", "KJ-"), ("无侦-", "WZ-"), ("歼-", "J-"), ("轰-", "H-"), ("运-", "Y-"), ("直-", "Z-")]
_SERVICE = {"英国": "RAF", "澳大利亚": "RAAF", "韩国": "ROKN", "印度": "IN", "新西兰": "RNZAF", "加拿大": "RCAF",
            "意大利": "ITAF", "台湾": "ROCAF", "德国": "GAF", "法国": "FN", "新加坡": "RSAF", "马来西亚": "RMAF",
            "菲律宾": "PAF", "越南": "VPAF", "俄罗斯": "RUAF"}
_US_ORIGIN = ("P-8", "MH-60", "RC-135", "E-7", "F-35", "EA-18", "MQ-4", "RQ-4", "E-2", "F/A-18", "C-130", "KC-")
_CALLSIGN = {("新加坡", "G550空中预警机"): "G550-AEW", ("中国", "直-20舰载反潜直升机"): "Z-20F"}


def callsign(e: Event) -> str:
    if (e.country, e.platform) in _CALLSIGN:
        return _CALLSIGN[(e.country, e.platform)]
    code = re.match(r"^[“”]?([A-Za-z0-9\-/]+|[一-龥]+-\d+[A-Z]*)", e.platform.replace("“", "").replace("”", ""))
    code = code.group(1) if code else e.platform[:6]
    for a, b in _CN_PREFIX:
        if code.startswith(a):
            return b + code[len(a):]
    if e.country not in ("美国", "日本", "中国") and code.startswith(_US_ORIGIN):
        return f"{_SERVICE.get(e.country, 'AF')}-{code.replace('-', '')}"
    return code


def task_desc(e: Event) -> str:
    body = e.intel_body or (f"{e.day}，{e.country}{e.platform}{action_phrase(e)}，执行{e.task}，"
                            f"时间为{time_span(e)}。")
    return body[:50] + "..." if len(body) > 50 else body


def _remark(e: Event, ship: bool) -> str:
    title = e.intel_title or (e.opinions[0][1] if e.opinions else f"{e.country}{e.platform}{action_phrase(e)}")
    title = re.sub(r"（组.+?）$", "", title)
    t = title[:23] + "..." if len(title) > 23 else title
    if ship:
        return f"关联舆情{len(e.opinions)}条；{t}"
    media = "、".join(OrderedDict.fromkeys(m for m, _ in e.opinions)) or "无"
    return f"关联舆情：{media}；{t}"


def remark(e: Event) -> str:
    return _remark(e, ship=e.kind == "ship")
