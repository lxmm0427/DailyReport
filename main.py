"""日报生成入口。

用法：
    python main.py --data 数据 --out 日报                     # 生成全部初赛节点
    python main.py --data 数据 --out 日报 --nodes 2025.5.10   # 指定节点
    python main.py --zip                                       # 另外打包 日报.zip
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from dailyreport.charts import make_charts  # noqa: E402
from dailyreport.events import fmt_day, parse_day  # noqa: E402
from dailyreport.pipeline import dump_audit, history_until  # noqa: E402
from dailyreport.writers import write_docx, write_xlsx  # noqa: E402

PRELIM_NODES = ["2025.5.10", "2025.5.18", "2025.5.30", "2025.6.9", "2025.6.17", "2025.6.29", "2025.7.9", "2025.7.17"]


def run_node(data: Path, out: Path, node: str, cache: dict, audit: Path | None = None) -> Path:
    hist = history_until(data, node, cache)
    if not hist or hist[-1].day != node:
        raise SystemExit(f"数据中缺少节点 {node}")
    today = hist[-1]
    prev_day = fmt_day(parse_day(node).fromordinal(parse_day(node).toordinal() - 1))
    prev = next((h.events for h in hist if h.day == prev_day), None)
    d = out / node
    d.mkdir(parents=True, exist_ok=True)
    charts = make_charts(node, today.events, d / "附件图表")
    write_xlsx(node, today.events, d / f"{node}机舰活动明细.xlsx")
    write_docx(node, today.events, prev, [(h.day, h.events) for h in hist], charts, d / f"{node}日报.docx")
    if audit:
        audit.mkdir(parents=True, exist_ok=True)
        dump_audit(today, audit / f"{node}_核验记录.json")
    return d


def main() -> None:
    ap = argparse.ArgumentParser(description="多源海空态势日报生成")
    ap.add_argument("--data", default="数据", type=Path)
    ap.add_argument("--out", default="outputs/日报", type=Path)
    ap.add_argument("--nodes", nargs="*", default=PRELIM_NODES)
    ap.add_argument("--audit", default="outputs/audit", type=Path, help="核验记录输出目录")
    ap.add_argument("--zip", action="store_true", help="打包为 <out>.zip")
    args = ap.parse_args()
    cache: dict = {}
    for node in args.nodes:
        d = run_node(args.data, args.out, node, cache, args.audit)
        print("生成", d)
    if args.zip:
        z = shutil.make_archive(str(args.out), "zip", root_dir=args.out.parent, base_dir=args.out.name)
        print("打包", z)


if __name__ == "__main__":
    main()
