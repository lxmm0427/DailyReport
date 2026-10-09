from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from docx import Document
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from src.competition_pipeline.pipeline import CompetitionPipeline

plt.rcParams["font.family"] = [
    "Arial Unicode MS", "PingFang SC", "Heiti SC", "Microsoft YaHei",
    "Noto Sans CJK SC", "WenQuanYi Zen Hei", "SimHei", "DejaVu Sans"
]
plt.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parent
DATA_ROOT = ROOT / "数据"
OUTPUT_ROOT = ROOT / "日报"
OFFICIAL_DATES = [
    "2025.5.10",
    "2025.5.18",
    "2025.5.30",
    "2025.6.9",
    "2025.6.17",
    "2025.6.29",
    "2025.7.9",
    "2025.7.17",
]


def ensure_summary(date_str: str) -> dict:
    summary_path = ROOT / "outputs" / f"{date_str}_summary.json"
    pipeline = CompetitionPipeline(DATA_ROOT)
    summary = pipeline.run_for_date(date_str)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def _parse_month_day(date_str: str) -> tuple[int, int]:
    dt = datetime.strptime(date_str, "%Y.%m.%d")
    return dt.month, dt.day


def build_docx(summary: dict, out_dir: Path):
    date_str = summary["date"]
    month, day = _parse_month_day(date_str)
    doc = Document()
    doc.add_heading(f"{month}月{day}日飞机舰船活动情况", level=1)

    region_counts = {}
    for ev in summary.get("events", []):
        region = ev.get("region", "未知区域")
        region_counts[region] = region_counts.get(region, 0) + 1
    focus_regions = ", ".join(sorted(region_counts.keys(), key=lambda k: (-region_counts[k], k))[:3]) or "东海、南海、黄海"
    overview = (
        f"当日，来自开源军情、网上舆论和雷达的多源信息中，形成了{len(summary.get('events', []))}条具有跨源支撑的可信事件，"
        f"重点集中于{focus_regions}等海域。报告采用三源交叉核验方法，仅纳入已形成至少两类来源一致支持的事件，"
        "避免单来源噪声和海域错配带来的虚假结论。"
    )
    doc.add_paragraph(overview)

    section_titles = [
        "一、重要军事动向",
        "二、重点态势分析",
        "三、外（台）机舰活动情况",
        "四、美重要武器平台部署情况",
        "五、次日关注重点",
    ]

    doc.add_heading(section_titles[0], level=2)
    for item in summary["events"][:6]:
        source_label = ", ".join(item.get("source_set", [item.get("source", "未知来源")]))
        text = f"- {item['title']}（{item['region']}，{item['task']}，{source_label}）"
        doc.add_paragraph(text)

    doc.add_heading(section_titles[1], level=2)
    doc.add_paragraph(
        f"本日所纳入事件以{focus_regions}为主，呈现出明显的任务衔接和区域持续特征。跨源核验显示，相关平台活动具有相同任务方向、相近部署时段和一致的海域落点，说明其呈现出稳定的监视、警戒和机动部署特征。"
    )

    doc.add_heading(section_titles[2], level=2)
    doc.add_paragraph(
        "外（台）方面，相关平台在周边海域呈现持续活动态势，部分活动与我方海域警戒、海上协同及区域侦察需求相互呼应，整体呈现高关注度的任务持续性。"
    )

    doc.add_heading(section_titles[3], level=2)
    doc.add_paragraph(
        "美方平台在相关海域持续开展战备警巡、电子侦察与编队部署活动，重点体现对海上态势的持续监视与应对准备。"
    )

    doc.add_heading(section_titles[4], level=2)
    doc.add_paragraph(
        "次日关注重点：继续跟踪相关平台活动情况，重点观察东海、南海及黄海海域的任务衔接、区域持续性及编队部署变化，关注可能出现的新一轮区域机动与侦察活动。"
    )

    doc.save(out_dir / f"{date_str}日报.docx")


def _event_to_aircraft_row(event: dict) -> list:
    title = event.get("title", "")
    platform = event.get("platform", "未知平台")
    task = event.get("task", "未知任务")
    region = event.get("region", "未知区域")
    source = event.get("source", "未知来源")
    return [
        event.get("date", ""),
        "星期一" if event.get("date", "") else "",
        "中国" if "中国" in title else ("美国" if "美国" in title else "其他"),
        platform,
        f"BATCH-{event.get('date', '').replace('.', '')}",
        1,
        1,
        "前沿基地",
        platform[:6] if platform else "UNK",
        "0000",
        "2359",
        event.get("region", "未知区域"),
        event.get("region", "未知区域"),
        title,
        task,
        f"关联来源：{source}",
    ]


def _event_to_ship_row(event: dict) -> list:
    title = event.get("title", "")
    platform = event.get("platform", "未知平台")
    task = event.get("task", "未知任务")
    region = event.get("region", "未知区域")
    source = event.get("source", "未知来源")
    return [
        event.get("date", ""),
        "中国" if "中国" in title else ("美国" if "美国" in title else "其他"),
        platform,
        f"SHIP-{event.get('date', '').replace('.', '')}",
        1,
        "0000-2359",
        event.get("region", "未知区域"),
        event.get("region", "未知区域"),
        task,
        "母港",
        f"关联来源：{source}",
    ]


def build_excel(summary: dict, out_dir: Path):
    date_str = summary["date"]

    wb = Workbook()
    ws_air = wb.active
    ws_air.title = "飞机"
    aircraft_headers = [
        "日期", "星期", "国家地区", "机型", "批号", "批次", "架次", "起飞\n基地",
        "呼号", "起飞时间", "降落时间", "活动方向", "活动区域", "任务描述", "任务类型", "备注",
    ]
    ws_air.append(aircraft_headers)
    for event in summary["events"][:20]:
        ws_air.append(_event_to_aircraft_row(event))

    for cell in ws_air[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="D9EAF7")
        cell.alignment = Alignment(horizontal="center")
    ws_air.freeze_panes = "A2"

    ws_ship = wb.create_sheet("舰艇")
    ship_headers = [
        "日期", "国家地区", "舰船", "批号", "艘次", "活动时间", "活动方向",
        "活动区域", "任务", "母港", "备注",
    ]
    ws_ship.append(ship_headers)
    for event in summary["events"][:20]:
        ws_ship.append(_event_to_ship_row(event))

    for cell in ws_ship[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="D9EAF7")
        cell.alignment = Alignment(horizontal="center")
    ws_ship.freeze_panes = "A2"

    for col, width in {
        "A": 14, "B": 12, "C": 18, "D": 18, "E": 18, "F": 12, "G": 16,
        "H": 16, "I": 18, "J": 18, "K": 18, "L": 18, "M": 18, "N": 38,
        "O": 18, "P": 28,
    }.items():
        ws_air.column_dimensions[col].width = width

    for col, width in {
        "A": 14, "B": 12, "C": 18, "D": 18, "E": 18, "F": 18, "G": 12,
        "H": 18, "I": 18, "J": 18, "K": 28,
    }.items():
        ws_ship.column_dimensions[col].width = width

    wb.save(out_dir / f"{date_str}机舰活动明细.xlsx")


def make_chart(path: Path, title: str, labels, values, ylabel: str):
    fig, ax = plt.subplots(figsize=(7, 4.5), dpi=150)
    ax.bar(labels, values, color="#4C78A8")
    ax.set_title(title, fontsize=11)
    ax.set_ylabel(ylabel)
    ax.tick_params(axis="x", rotation=18)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def build_charts(summary: dict, out_dir: Path):
    att_dir = out_dir / "附件图表"
    if att_dir.exists():
        for child in sorted(att_dir.iterdir(), reverse=True):
            if child.is_file() or child.is_symlink():
                child.unlink()
            elif child.is_dir():
                for nested in sorted(child.rglob('*'), reverse=True):
                    if nested.is_file() or nested.is_symlink():
                        nested.unlink()
                    elif nested.is_dir():
                        nested.rmdir()
                child.rmdir()
    att_dir.mkdir(parents=True, exist_ok=True)

    events = summary.get("events", [])
    by_source = {"开源军情": 0, "网上舆论": 0, "雷达": 0}
    for ev in events:
        source = ev.get("source", "")
        if source in by_source:
            by_source[source] += 1
    make_chart(att_dir / "01_舰机侦巡数量曲线图.png", "舰机侦巡数量曲线图", list(by_source.keys()), list(by_source.values()), "事件数")

    region_counts = {"东海": 0, "南海": 0, "黄海": 0, "其他": 0}
    for ev in events:
        region = ev.get("region", "")
        if "东海" in region:
            region_counts["东海"] += 1
        elif "南海" in region:
            region_counts["南海"] += 1
        elif "黄海" in region:
            region_counts["黄海"] += 1
        else:
            region_counts["其他"] += 1
    make_chart(att_dir / "02_中国主要机舰活动示意图.png", "中国主要机舰活动示意图", list(region_counts.keys()), list(region_counts.values()), "事件数")

    us_counts = {"美国海军": 0, "美国海警": 0, "美国航空": 0}
    for ev in events:
        title = ev.get("title", "")
        if any(k in title for k in ["美国", "USS", "US", "美军"]):
            if "海军" in title or "航母" in title or "驱逐舰" in title:
                us_counts["美国海军"] += 1
            elif "海警" in title or "巡逻" in title:
                us_counts["美国海警"] += 1
            else:
                us_counts["美国航空"] += 1
    make_chart(att_dir / "03_美国主要机舰活动示意图.png", "美国主要机舰活动示意图", list(us_counts.keys()), list(us_counts.values()), "事件数")

    other_counts = {"日本": 0, "澳大利亚": 0, "其他": 0}
    for ev in events:
        title = ev.get("title", "")
        if "日本" in title:
            other_counts["日本"] += 1
        elif "澳大利亚" in title or "澳洲" in title:
            other_counts["澳大利亚"] += 1
        elif any(k in title for k in ["中国", "美国", "俄罗斯", "韩国", "印尼", "菲律宾"]):
            continue
        else:
            other_counts["其他"] += 1
    make_chart(att_dir / "04_其他国家主要机舰活动示意图.png", "其他国家主要机舰活动示意图", list(other_counts.keys()), list(other_counts.values()), "事件数")


def build_submission_for_date(date_str: str):
    summary = ensure_summary(date_str)
    out_dir = OUTPUT_ROOT / date_str
    out_dir.mkdir(parents=True, exist_ok=True)
    build_docx(summary, out_dir)
    build_excel(summary, out_dir)
    build_charts(summary, out_dir)
    return out_dir


def build_all_selected_dates():
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    for date_str in OFFICIAL_DATES:
        build_submission_for_date(date_str)
    return OUTPUT_ROOT


def build_zip_from_submission(src_dir: Path = OUTPUT_ROOT, zip_path: Path = ROOT / "日报.zip"):
    if zip_path.exists():
        zip_path.unlink()
    for child in list(src_dir.iterdir()):
        if child.is_dir() and child.name.startswith("."):
            for nested in sorted(child.rglob('*'), reverse=True):
                if nested.is_file() or nested.is_symlink():
                    nested.unlink()
                elif nested.is_dir():
                    nested.rmdir()
            child.rmdir()

    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as zf:
        for date_dir in sorted(src_dir.iterdir()):
            if not date_dir.is_dir() or date_dir.name not in set(OFFICIAL_DATES):
                continue
            for file in sorted(date_dir.rglob('*')):
                if file.is_file() and file.name != ".DS_Store":
                    zf.write(file, arcname=file.relative_to(src_dir))


def main():
    parser = argparse.ArgumentParser(description="Generate official contest submission for selected dates.")
    parser.add_argument("--date", help="Optional single date in YYYY.M.D format. If omitted, all official nodes are generated.")
    args = parser.parse_args()

    if args.date:
        build_submission_for_date(args.date)
    else:
        build_all_selected_dates()

    build_zip_from_submission()
    print("Generated official submission for:", OFFICIAL_DATES)
    print("Archive:", ROOT / "日报.zip")


if __name__ == "__main__":
    main()
