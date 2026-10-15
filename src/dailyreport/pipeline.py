"""按日处理与研判节点调度。研判某节点时只读取赛段起始日至节点当日的数据。"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

from .events import Event, build_events, parse_day
from .link import Candidate, adjudicate, link_day
from .radar import load_day_radar
from .textparse import load_day_texts


@dataclass
class DayResult:
    day: str
    candidates: list[Candidate]
    events: list[Event]


def list_days(data_root: Path) -> list[str]:
    days = [p.name for p in data_root.iterdir() if p.is_dir() and p.name[:4].isdigit()]
    return sorted(days, key=parse_day)


def process_day(data_root: Path, day: str) -> DayResult:
    d = data_root / day
    cands = [adjudicate(c) for c in link_day(load_day_radar(d), load_day_texts(d))]
    return DayResult(day, cands, build_events(cands))


def history_until(data_root: Path, node: str, cache: dict[str, DayResult] | None = None,
                  start_date: str | None = None) -> list[DayResult]:
    """返回赛段起始日至节点当日（含）的逐日结果；节点之后的数据不读取。"""
    cache = cache if cache is not None else {}
    nd = parse_day(node)
    start = parse_day(start_date) if start_date is not None else None
    if start is not None and start > nd:
        raise ValueError(f"赛段起始日 {start_date} 晚于研判节点 {node}")
    out = []
    for day in list_days(data_root):
        date = parse_day(day)
        if date > nd:
            break
        if start is not None and date < start:
            continue
        if day not in cache:
            cache[day] = process_day(data_root, day)
        out.append(cache[day])
    return out


def dump_audit(res: DayResult, path: Path) -> None:
    """保存逐批号核验记录（证据与冲突），便于复查。"""
    rows = []
    for c in res.candidates:
        rows.append(dict(
            batch=c.seg.batch, kind=c.seg.kind, country=c.seg.country, platform=c.seg.platform,
            time=f"{c.seg.start}-{c.seg.end}", radar_regions=[a["region"] for a in c.seg.alts], region=c.region,
            verdict=c.verdict, reasons=c.reasons,
            evidence=[dict(source=e.mention.source, file=e.mention.file, agree=e.agree, conflict=e.conflict)
                      for e in c.evidence],
        ))
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
