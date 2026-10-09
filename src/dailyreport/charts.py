"""附件图表：01 舰机侦巡数量曲线图；02-04 中/美/其他国家主要机舰活动示意图（时段甘特图）。"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

from .analysis import core, hourly_counts  # noqa: E402
from .events import Event, parse_day  # noqa: E402

AIR_COLOR, SHIP_COLOR = "#c0392b", "#1f5f8b"
AIR_BAR, SHIP_BAR = "#d35400", "#2874a6"
_CJK = ["Arial Unicode MS", "PingFang SC", "Heiti SC", "STHeiti", "Songti SC", "Noto Sans CJK SC",
        "Noto Sans SC", "Source Han Sans SC", "SimHei", "Microsoft YaHei", "WenQuanYi Zen Hei"]


def _setup_font() -> None:
    have = {f.name for f in font_manager.fontManager.ttflist}
    picked = [f for f in _CJK if f in have]
    plt.rcParams["font.sans-serif"] = picked + plt.rcParams["font.sans-serif"]
    plt.rcParams["axes.unicode_minus"] = False


def plot_counts(day: str, events: list[Event], path: Path) -> None:
    _setup_font()
    air, ship = hourly_counts(events)
    d = parse_day(day)
    fig, ax = plt.subplots(figsize=(12.1, 5.4), dpi=200)
    xs = list(range(24))
    ax.plot(xs, air, color=AIR_COLOR, marker="o", lw=2.2, ms=6, label="飞机架次")
    ax.plot(xs, ship, color=SHIP_COLOR, marker="s", lw=2.2, ms=6, label="舰艇艘次")
    ax.set_xticks(xs, [f"{h:02d}:00" for h in xs], rotation=45, ha="right")
    ax.set_xlabel("时段")
    ax.set_ylabel("数量（架次/艘次）")
    ax.yaxis.get_major_locator().set_params(integer=True)
    ax.set_ylim(bottom=-0.3)
    ax.grid(True, ls="--", alpha=0.35)
    ax.legend(loc="upper right")
    ax.set_title(f"{d.month}月{d.day}日舰机侦巡数量曲线图", fontsize=16)
    fig.tight_layout()
    fig.savefig(path, format="png")
    plt.close(fig)


def plot_gantt(day: str, events: list[Event], title: str, path: Path) -> None:
    _setup_font()
    evs = sorted(core(events), key=lambda e: (e.start, e.kind, e.platform))
    n = max(len(evs), 1)
    fig, ax = plt.subplots(figsize=(10.9, max(2.6, 0.45 * n + 1.6)), dpi=200)
    for i, e in enumerate(evs):
        s, t = e.minutes()
        ax.barh(i, (t - s) / 60, left=s / 60, height=0.55,
                color=AIR_BAR if e.kind == "air" else SHIP_BAR, alpha=0.85)
        label = f"{e.region} / {e.direction} / {e.task}"
        if t / 60 > 18.5:   # 靠右的柱子把标签放在左侧，避免超出画布
            ax.text(s / 60 - 0.1, i, label, va="center", ha="right", fontsize=8)
        else:
            ax.text(t / 60 + 0.1, i, label, va="center", fontsize=8)
    ax.set_yticks(range(len(evs)),
                  [f"{'飞机' if e.kind == 'air' else '舰艇'} | {e.country} | {e.platform}({e.count})" for e in evs],
                  fontsize=8)
    if not evs:
        ax.text(12, 0, "当日无可信活动", ha="center", va="center", fontsize=12)
        ax.set_yticks([])
    ax.set_ylim(-0.7, n - 0.3)
    ax.invert_yaxis()
    ax.set_xlim(0, 24)
    ax.set_xticks(range(0, 25, 2), [f"{h:02d}:00" for h in range(0, 25, 2)])
    ax.set_xlabel("时段")
    ax.grid(True, axis="x", ls="--", alpha=0.35)
    ax.legend(handles=[Patch(color=AIR_BAR, label="飞机"), Patch(color=SHIP_BAR, label="舰艇")],
              loc="upper left", bbox_to_anchor=(1.005, 1.0), borderaxespad=0)
    ax.set_title(title, fontsize=15)
    fig.tight_layout()
    fig.savefig(path, format="png")
    plt.close(fig)


def make_charts(day: str, events: list[Event], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    d = parse_day(day)
    date = f"{d.year}年{d.month}月{d.day}日"
    paths = [out_dir / "01_舰机侦巡数量曲线图.png", out_dir / "02_中国主要机舰活动示意图.png",
             out_dir / "03_美国主要机舰活动示意图.png", out_dir / "04_其他国家主要机舰活动示意图.png"]
    plot_counts(day, events, paths[0])
    plot_gantt(day, [e for e in events if e.country == "中国"], f"{date}中国主要机舰活动示意图", paths[1])
    plot_gantt(day, [e for e in events if e.country == "美国"], f"{date}美国主要机舰活动示意图", paths[2])
    plot_gantt(day, [e for e in events if e.country not in ("中国", "美国")],
               f"{date}{other_countries_label(events)}其他国家主要机舰活动示意图", paths[3])
    return paths


def other_countries_label(events: list[Event]) -> str:
    """官方样例图题固定写作“日、加等其他国家”。"""
    return "日、加等"
