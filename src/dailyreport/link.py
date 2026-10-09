"""跨源关联与可信判定。

候选事件 = 雷达航迹段。每条文本按“平台 + 时间/区域/任务”等要素与当日候选打分，
挂到最匹配的航迹段上，再逐字段比较一致/冲突：
  - 至少一条文本与雷达在关键事实上相互支持（雷达 + 文本 = 两类来源）；
  - 任何关联来源在主体、平台类别、区域、时间、数量、任务上不得给出明确冲突值。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import lexicon as L
from .radar import Segment
from .textparse import Mention

GENERIC = {"东海", "南海", "黄海"}
REGION_TOL = 0.9      # 飞机坐标距文本区域锚点的容差（度）
TIME_TOL = 10         # 时间容差（分钟）


def _mins(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[2:])


@dataclass
class Evidence:
    mention: Mention
    agree: list[str] = field(default_factory=list)
    conflict: list[str] = field(default_factory=list)

    @property
    def score(self) -> float:
        return len(self.agree) - 2 * len(self.conflict)


@dataclass
class Candidate:
    seg: Segment
    evidence: list[Evidence] = field(default_factory=list)
    region: str | None = None        # 判定后的活动区域
    direction: str | None = None
    relation: str = "活动"
    verdict: str = "未核验"           # 可信 / 冲突 / 单源 / 范围外
    reasons: list[str] = field(default_factory=list)

    @property
    def sources(self) -> set[str]:
        return {"雷达"} | {e.mention.source for e in self.evidence}


# ---------------------------------------------------------------- 字段比较
def _alt_region_relation(kind: str, alt: dict, text_region: str | None, text_dir: str | None) -> str | None:
    """单条子航迹与文本区域的关系：'agree' / 'conflict' / None(文本无区域信息)。"""
    if not text_region and not text_dir:
        return None
    rr = alt["region"]
    rdir = L.region_direction(rr)
    if not text_region:
        return "agree" if text_dir == rdir else "conflict"
    tdir = L.region_direction(text_region)
    if text_region == rr:
        return "agree"
    # 一方是方向级泛称（东海/南海/黄海），另一方在该方向内 → 一致
    if text_region in GENERIC or rr in GENERIC:
        return "agree" if tdir == rdir and rdir != "其他" else "conflict"
    if kind == "air":
        # 飞机区域由坐标推断，相邻锚点可能混淆，按距离判断
        d = L.anchor_distance(text_region, alt["lon"], alt["lat"])
        if d is not None:
            return "agree" if d < REGION_TOL else "conflict"
    return "conflict"


def region_relation(seg: Segment, text_region: str | None, text_dir: str | None) -> tuple[str | None, int | None]:
    """返回 (关系, 一致的子航迹下标)。任一子航迹一致即视为一致。"""
    rels = [_alt_region_relation(seg.kind, a, text_region, text_dir) for a in seg.alts]
    if all(r is None for r in rels):
        return None, None
    for i, r in enumerate(rels):
        if r == "agree":
            return "agree", i
    return "conflict", None


def compare(seg: Segment, m: Mention) -> Evidence:
    ev = Evidence(m)
    if m.country:
        (ev.agree if m.country == seg.country else ev.conflict).append("主体")
    if seg.platform in m.platforms:
        ev.agree.append("平台")
    if m.kind_conflict:
        ev.conflict.append("平台类别")
    rel, _ = region_relation(seg, m.region, m.direction)
    if rel:
        (ev.agree if rel == "agree" else ev.conflict).append("区域")
    if m.start and m.end:
        ok = abs(_mins(m.start) - _mins(seg.start)) <= TIME_TOL and abs(_mins(m.end) - _mins(seg.end)) <= TIME_TOL
        (ev.agree if ok else ev.conflict).append("时间")
    elif m.start:
        ok = abs(_mins(m.start) - _mins(seg.start)) <= TIME_TOL
        (ev.agree if ok else ev.conflict).append("时间")
    if m.task:
        (ev.agree if m.task == seg.task else ev.conflict).append("任务")
    if m.count and m.unit and len(m.platforms) <= 1:
        # 文本未写数量时 extract 默认 1，这里只比较明确写出的数量
        if _explicit_count(m):
            (ev.agree if m.count == seg.count else ev.conflict).append("数量")
    return ev


def _explicit_count(m: Mention) -> bool:
    import re
    return bool(re.search(r"(\d+|[一两二三四五六七八九十])\s*(架次|架|艘次|艘)", m.body))


# ---------------------------------------------------------------- 关联
def link_day(segs: list[Segment], mentions: list[Mention]) -> list[Candidate]:
    """按（来源, 平台）分组做一对一最优匹配：同一来源的一篇文本只描述一个事件，
    同一事件在同一来源中至多取一篇主证据，避免同型平台同日多次活动被错误合并。"""
    import numpy as np
    from scipy.optimize import linear_sum_assignment

    cands = [Candidate(s) for s in segs]
    by_platform: dict[str, list[Candidate]] = {}
    for c in cands:
        by_platform.setdefault(c.seg.platform, []).append(c)

    groups: dict[tuple[str, str], list[Mention]] = {}
    for m in mentions:
        for p in m.platforms:
            if p in by_platform:
                groups.setdefault((m.source, p), []).append(m)

    for (_, p), ms in groups.items():
        pool = by_platform[p]
        evs = [[compare(c.seg, m) for c in pool] for m in ms]
        big = 1e6
        cost = np.full((len(ms), len(pool)), big)
        for i, row in enumerate(evs):
            for j, ev in enumerate(row):
                # 至少要在时间或区域上对得上，才视为在描述同一事件
                if {"时间", "区域"} & set(ev.agree):
                    cost[i, j] = -ev.score
        ri, ci = linear_sum_assignment(cost)
        for i, j in zip(ri, ci):
            if cost[i, j] < big:
                pool[j].evidence.append(evs[i][j])
    return cands


# ---------------------------------------------------------------- 判定
def adjudicate(c: Candidate) -> Candidate:
    seg = c.seg
    # 区域：先选被文本支持的子航迹，再取与之一致的最具体文本区域
    votes: dict[int, int] = {}
    for e in c.evidence:
        _, i = region_relation(seg, e.mention.region, e.mention.direction)
        if i is not None:
            votes[i] = votes.get(i, 0) + 1
    alt = seg.alts[max(votes, key=votes.get)] if votes else seg.alts[0]
    c.region = alt["region"]
    specific = [e.mention.region for e in c.evidence if e.mention.region and e.mention.region not in GENERIC
                and _alt_region_relation(seg.kind, alt, e.mention.region, None) == "agree"]
    if specific and (c.region in GENERIC or seg.kind == "air"):
        c.region = specific[0]
    c.direction = L.region_direction(c.region)

    rels = [e.mention.relation for e in c.evidence if e.mention.relation]
    c.relation = "离开" if "离开" in rels else ("进入" if "进入" in rels else "活动")

    conflicts = sorted({f"{e.mention.source}:{x}" for e in c.evidence for x in e.conflict})
    supports = [e for e in c.evidence if len(e.agree) >= 2 and not e.conflict]
    if seg.n_segs > 1:
        c.reasons.append(f"批号混入{seg.n_segs}条子航迹，取{c.region}")
    if conflicts:
        c.verdict = "冲突"
        c.reasons += conflicts
    elif not supports:
        c.verdict = "单源"
    elif c.direction == "其他":
        c.verdict = "范围外"
    else:
        c.verdict = "可信"
    return c
