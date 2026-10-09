"""雷达信息表解析：按批号聚合成航迹段，并标记噪声。

同一批号下可能混入漂移/错配的子航迹（开始经纬度或活动区域不同、时间交错）。
每个批号作为一个候选，子航迹记录在 alts 中，由跨源核验选出被文本支持的那一条。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from pathlib import Path

import pandas as pd


def _hhmm(ts: str) -> str:
    return ts[11:13] + ts[14:16]


def _minutes(ts: str) -> int:
    return int(ts[11:13]) * 60 + int(ts[14:16])


def haversine_km(lon1, lat1, lon2, lat2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@dataclass
class Segment:
    kind: str                   # air / ship
    day: str                    # 2025.5.10
    batch: str
    seg: int                    # 同批号内的段序号
    n_segs: int                 # 同批号的段数（>1 说明批号混入异常航迹）
    country: str
    platform: str
    task: str
    count: int
    start: str                  # HHMM
    end: str
    base: str                   # 起飞机场 / 出航港口
    hull: str = ""              # 舷号（舰船）
    region: str | None = None   # 舰船活动区域；飞机由坐标推断
    lon: float | None = None    # 航迹中心
    lat: float | None = None
    start_lon: float | None = None
    start_lat: float | None = None
    n_points: int = 0
    flags: list[str] = field(default_factory=list)
    # 同批号下的子航迹 [{region, lon, lat, n, start, end}]，多于 1 条说明混入漂移/错配点
    alts: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _day_of(path: Path) -> str:
    return path.parent.name


def load_air(xlsx: Path) -> list[Segment]:
    from .lexicon import nearest_region
    df = pd.read_excel(xlsx, sheet_name="飞机", dtype={"批号": str})
    day = _day_of(xlsx)
    out = []
    for batch, g in df.groupby("批号", sort=False):
        g = g.sort_values("位置时间")
        alts = []
        for (x, y), s in g.groupby(["开始经度", "开始纬度"], sort=False):
            region, dist = nearest_region(float(x), float(y))
            alts.append(dict(region=region, dist=round(dist, 3), lon=float(x), lat=float(y), n=len(s),
                             start=_hhmm(s["位置时间"].iloc[0]), end=_hhmm(s["位置时间"].iloc[-1])))
        alts.sort(key=lambda a: -a["n"])
        main = alts[0]
        seg = Segment(
            kind="air", day=day, batch=batch, seg=0, n_segs=len(alts),
            country=_mode(g["国家地区"]), platform=_mode(g["目标类型"]), task=_mode(g["任务"]),
            count=int(_mode(g["目标数量"])), start=_hhmm(g["位置时间"].iloc[0]), end=_hhmm(g["位置时间"].iloc[-1]),
            base=_mode(g["起飞机场"]), region=main["region"], lon=float(g["经度"].median()),
            lat=float(g["纬度"].median()), start_lon=main["lon"], start_lat=main["lat"], n_points=len(g), alts=alts,
        )
        seg.flags = _air_flags(g, day)
        out.append(seg)
    return out


def load_ship(xlsx: Path) -> list[Segment]:
    df = pd.read_excel(xlsx, sheet_name="舰船", dtype={"批号": str, "机弦号": str})
    day = _day_of(xlsx)
    out = []
    for batch, g in df.groupby("批号", sort=False):
        alts = [dict(region=r, n=len(s), start=_hhmm(_mode(s["首点时间"])), end=_hhmm(_mode(s["结束时间"])))
                for r, s in g.groupby("活动区域", sort=False)]
        alts.sort(key=lambda a: -a["n"])
        seg = Segment(
            kind="ship", day=day, batch=batch, seg=0, n_segs=len(alts),
            country=_mode(g["国家地区"]), platform=_mode(g["机舰名"]), task=_mode(g["任务"]),
            count=int(_mode(g["数量"])), start=_hhmm(_mode(g["首点时间"])), end=_hhmm(_mode(g["结束时间"])),
            base=_mode(g["出航港口"]), hull=str(_mode(g["机弦号"])), region=alts[0]["region"], n_points=len(g),
            alts=alts,
        )
        seg.flags = _ship_flags(g, day)
        out.append(seg)
    return out


def _mode(s: pd.Series):
    return s.mode().iloc[0] if len(s) else None


def _same_day(ts: str, day: str) -> bool:
    y, m, d = day.split(".")
    return ts.startswith(f"{y}.{int(m):02d}.{int(d):02d}")


def _air_flags(s: pd.DataFrame, day: str) -> list[str]:
    flags = []
    if not all(_same_day(t, day) for t in s["位置时间"]):
        flags.append("时间跨日")
    # 轨迹跳变：相邻点隐含速度远超飞行速度
    pts = s[["位置时间", "经度", "纬度"]].values.tolist()
    for (t1, x1, y1), (t2, x2, y2) in zip(pts, pts[1:]):
        dt = max(_minutes(t2) - _minutes(t1), 1) / 60
        if haversine_km(x1, y1, x2, y2) / dt > 1500:
            flags.append("轨迹跳变")
            break
    for col in ("国家地区", "目标类型", "任务"):
        if s[col].nunique() > 1:
            flags.append(f"{col}不一致")
    return flags


def _ship_flags(s: pd.DataFrame, day: str) -> list[str]:
    flags = []
    if not all(_same_day(t, day) for t in s["首点时间"]):
        flags.append("时间跨日")
    if (s["首点时间"] > s["结束时间"]).any():
        flags.append("时间倒置")
    for col in ("国家地区", "机舰名", "任务"):
        if s[col].nunique() > 1:
            flags.append(f"{col}不一致")
    return flags


def load_day_radar(day_dir: Path) -> list[Segment]:
    xs = list(day_dir.glob("雷达信息表_*.xlsx"))
    if not xs:
        return []
    return load_air(xs[0]) + load_ship(xs[0])
