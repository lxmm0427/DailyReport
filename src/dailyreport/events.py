"""可信事件：由通过核验的候选（雷达批号 + 文本证据）整理而成，供统计与成文使用。"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from .link import Candidate

WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def parse_day(day: str) -> dt.date:
    y, m, d = (int(x) for x in day.split("."))
    return dt.date(y, m, d)


def fmt_day(d: dt.date) -> str:
    return f"{d.year}.{d.month}.{d.day}"


@dataclass
class Event:
    day: str
    kind: str                  # air / ship
    country: str
    platform: str
    batch: str
    count: int
    start: str                 # HHMM
    end: str
    direction: str
    region: str
    task: str
    base: str
    relation: str              # 进入 / 活动 / 离开
    hull: str = ""
    intel_title: str = ""      # 关联开源军情
    intel_body: str = ""
    opinions: list[tuple[str, str]] = field(default_factory=list)   # (媒体, 标题)
    formation: list[str] = field(default_factory=list)              # 同一编队文本覆盖的批号
    formation_lead: str = ""   # 编队文本中的首个平台
    formation_order: list[str] = field(default_factory=list)       # 编队文本中的平台顺序
    sources: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)                  # 核验说明

    @property
    def date(self) -> dt.date:
        return parse_day(self.day)

    @property
    def weekday(self) -> str:
        return WEEKDAYS[self.date.weekday()]

    @property
    def foreign(self) -> bool:
        return self.country != "中国"

    @property
    def unit(self) -> str:
        return "架次" if self.kind == "air" else "艘"

    def minutes(self) -> tuple[int, int]:
        return int(self.start[:2]) * 60 + int(self.start[2:]), int(self.end[:2]) * 60 + int(self.end[2:])


def build_events(cands: list[Candidate]) -> list[Event]:
    trusted = [c for c in cands if c.verdict == "可信"]
    # 编队：同一篇文本同时挂到多个批号上
    by_mention: dict[int, list[Candidate]] = {}
    for c in trusted:
        for e in c.evidence:
            if len(e.mention.platforms) > 1:
                by_mention.setdefault(id(e.mention), []).append(c)

    out = []
    for c in trusted:
        s = c.seg
        intel = [e.mention for e in c.evidence if e.mention.source == "军情"]
        ops = [e.mention for e in c.evidence if e.mention.source == "舆论"]
        ev = Event(
            day=s.day, kind=s.kind, country=s.country, platform=s.platform, batch=s.batch, count=s.count,
            start=s.start, end=s.end, direction=c.direction, region=c.region, task=s.task, base=s.base,
            relation=c.relation, hull=s.hull,
            intel_title=intel[0].title if intel else "", intel_body=intel[0].body if intel else "",
            opinions=[(m.media or "网络媒体", m.title) for m in ops],
            sources=sorted(c.sources), notes=list(c.reasons),
        )
        for e in c.evidence:
            group = by_mention.get(id(e.mention))
            if group and len(group) > 1:
                ev.formation = [g.seg.batch for g in group]
                ev.formation_lead = e.mention.platforms[0]
                ev.formation_order = list(e.mention.platforms)
                if not ev.intel_title and e.mention.source == "军情":
                    ev.intel_title, ev.intel_body = e.mention.title, e.mention.body
        out.append(ev)
    # 编队成员若无单独舆情，继承编队主平台的舆情（与官方样例一致）
    by_batch = {e.batch: e for e in out}
    for e in out:
        if e.formation and not e.opinions:
            lead = next((by_batch[b] for b in e.formation if b in by_batch and by_batch[b].platform == e.formation_lead), None)
            if lead:
                e.opinions = list(lead.opinions)
    out.sort(key=lambda e: (e.kind != "air", e.start, e.country))
    return out
