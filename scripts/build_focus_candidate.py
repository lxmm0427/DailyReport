"""在基线日报上只替换第二节，并校验其余 40 个成果和 DOCX 其他 XML。

示例：
    PYTHONDONTWRITEBYTECODE=1 python scripts/build_focus_candidate.py

--history-json 可接收算法预先导出的逐日事件，用于没有 scipy 的文档运行时。
快照格式为 [{"day": "2025.5.1", "events": [dataclasses.asdict(event), ...]}, ...]。
该脚本不调用大模型、不重写 XLSX/PNG、不覆盖已有候选目录。
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import html
import io
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

sys.dont_write_bytecode = True
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

NODES = ("2025.5.10", "2025.5.18", "2025.5.30", "2025.6.9",
         "2025.6.17", "2025.6.29", "2025.7.9", "2025.7.17")
CHARTS = ("01_舰机侦巡数量曲线图.png", "02_中国主要机舰活动示意图.png",
          "03_美国主要机舰活动示意图.png", "04_其他国家主要机舰活动示意图.png")
SECOND_HEADING = "二、重点态势分析"
THIRD_HEADING = "三、外（台）机舰活动情况"
PARAGRAPH = re.compile(rb"<w:p(?:\s[^>]*)?>.*?</w:p>", re.S)
TEXT = re.compile(rb"(<w:t(?:\s[^>]*)?>)(.*?)(</w:t>)", re.S)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def expected_paths() -> list[str]:
    return [str(PurePosixPath("日报", node, name))
            for node in NODES
            for name in (f"{node}日报.docx", f"{node}机舰活动明细.xlsx",
                         *(f"附件图表/{chart}" for chart in CHARTS))]


def read_baseline(path: Path) -> dict[str, bytes]:
    expected = expected_paths()
    if path.is_dir():
        # The directory itself is 日报; only the required 48 products are read.
        members = {name: (path / PurePosixPath(name).relative_to("日报")).read_bytes()
                   for name in expected}
    else:
        with ZipFile(path) as archive:
            names = [entry.filename for entry in archive.infolist() if not entry.is_dir()]
            if len(names) != len(set(names)) or set(names) != set(expected):
                raise ValueError("基线 ZIP 必须恰含 48 个规定文件，且不得重名")
            members = {name: archive.read(name) for name in expected}
    if len(members) != 48:
        raise ValueError("基线成果数不是 48")
    return members


def paragraph_text(raw: bytes) -> str:
    return html.unescape(b"".join(match.group(2) for match in TEXT.finditer(raw)).decode("utf-8"))


def focus_block(xml: bytes) -> tuple[int, int, list[bytes]]:
    ET.fromstring(xml)  # Reject corrupt XML before any edit.
    paragraphs = list(PARAGRAPH.finditer(xml))
    seconds = [i for i, match in enumerate(paragraphs)
               if paragraph_text(match.group()) == SECOND_HEADING]
    thirds = [i for i, match in enumerate(paragraphs)
              if paragraph_text(match.group()) == THIRD_HEADING]
    if len(seconds) != 1 or len(thirds) != 1 or seconds[0] >= thirds[0]:
        raise ValueError("无法唯一定位第二节与第三节标题")
    first, last = seconds[0], thirds[0]
    start, end = paragraphs[first].end(), paragraphs[last].start()
    body = [match.group() for match in paragraphs[first + 1:last]]
    if not body or b"".join(body).strip() != xml[start:end].strip():
        raise ValueError("第二节含段落以外的结构，拒绝通用文本替换")
    return start, end, body


def replace_paragraph_text(template: bytes, text: str) -> bytes:
    # Preserve all paragraph and run properties verbatim, avoiding XML reserialization.
    if re.search(rb"<w:(?:drawing|pict|fldChar|instrText|br|tab)(?:\s|/|>)", template):
        raise ValueError("第二节段落模板含图形、字段或控制节点，不能安全替换")
    if not TEXT.search(template):
        raise ValueError("第二节段落模板没有文本节点")
    escaped = html.escape(text, quote=False).encode("utf-8")
    used = False

    def patch(match: re.Match[bytes]) -> bytes:
        nonlocal used
        result = match.group(1) + (escaped if not used else b"") + match.group(3)
        used = True
        return result

    return TEXT.sub(patch, template)


def patch_docx(original: bytes, paragraphs: list[str]) -> tuple[bytes, dict]:
    if not paragraphs or any(not isinstance(p, str) or not p.strip() for p in paragraphs):
        raise ValueError("新分析必须包含非空字符串段落")
    with ZipFile(io.BytesIO(original)) as source:
        old_xml = source.read("word/document.xml")
        start, end, templates = focus_block(old_xml)
        replacement = b"".join(replace_paragraph_text(templates[min(i, len(templates) - 1)], text)
                               for i, text in enumerate(paragraphs))
        new_xml = old_xml[:start] + replacement + old_xml[end:]
        ET.fromstring(new_xml)
        output = io.BytesIO()
        with ZipFile(output, "w") as target:
            target.comment = source.comment
            for entry in source.infolist():
                data = new_xml if entry.filename == "word/document.xml" else source.read(entry.filename)
                target.writestr(copy.copy(entry), data)
    candidate = output.getvalue()
    with ZipFile(io.BytesIO(original)) as old_zip, ZipFile(io.BytesIO(candidate)) as new_zip:
        if old_zip.namelist() != new_zip.namelist():
            raise AssertionError("DOCX 内部文件清单发生变化")
        identical_parts = all(old_zip.read(name) == new_zip.read(name)
                              for name in old_zip.namelist() if name != "word/document.xml")
        new_start, new_end, new_body = focus_block(new_zip.read("word/document.xml"))
    old_outside = old_xml[:start] + old_xml[end:]
    new_outside = new_xml[:new_start] + new_xml[new_end:]
    if not identical_parts or old_outside != new_outside:
        raise AssertionError("第二节之外的 XML 或其他 DOCX 部件发生变化")
    if [paragraph_text(p) for p in new_body] != paragraphs:
        raise AssertionError("候选第二节正文与算法输出不一致")
    return candidate, {
        "old_paragraphs": [paragraph_text(p) for p in templates],
        "new_paragraphs": paragraphs,
        "old_docx_sha256": sha256(original),
        "new_docx_sha256": sha256(candidate),
        "outside_section_xml_identical": True,
        "outside_section_xml_sha256": sha256(old_outside),
        "all_other_docx_parts_identical": True,
        "paragraph_and_run_properties_preserved": True,
    }


def load_history(data: Path, snapshot: Path | None):
    from dailyreport.events import Event, parse_day

    if snapshot:
        rows = json.loads(snapshot.read_text(encoding="utf-8"))
        if not isinstance(rows, list) or not rows:
            raise ValueError("逐日事件快照应为非空列表")
        history = []
        seen = set()
        for row in rows:
            day = row["day"]
            if day in seen:
                raise ValueError(f"快照日期重复：{day}")
            seen.add(day)
            events = [Event(**event) for event in row["events"]]
            if any(event.day != day for event in events):
                raise ValueError(f"快照中事件与所在日期不一致：{day}")
            # Node data must never read future records, even from a larger snapshot.
            if parse_day(day) <= parse_day(NODES[-1]):
                history.append((day, events))
        return sorted(history, key=lambda row: parse_day(row[0]))
    from dailyreport.pipeline import history_until

    return [(day.day, day.events) for day in history_until(data, NODES[-1])]


def raw_source_manifest(data: Path, history) -> list[dict]:
    entries = []
    for day, _events in history:
        folder = data / day
        if not folder.is_dir():
            raise ValueError(f"数据源目录缺失：{folder}")
        for path in sorted(folder.rglob("*")):
            if path.is_file() and path.suffix.lower() in (".txt", ".xlsx"):
                entries.append({"day": day, "path": str(path.relative_to(REPO_ROOT))
                                if path.is_relative_to(REPO_ROOT) else str(path.resolve()),
                                "sha256": sha256(path.read_bytes())})
    return entries


def reserve_output(requested: Path) -> Path:
    for suffix in range(1000):
        choice = requested if suffix == 0 else requested.with_name(f"{requested.name}_{suffix:02d}")
        try:
            choice.mkdir(parents=True, exist_ok=False)
            return choice
        except FileExistsError:
            continue
    raise FileExistsError("已存在过多同名候选目录，拒绝覆盖")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=REPO_ROOT / "outputs/日报.zip")
    parser.add_argument("--data", type=Path, default=REPO_ROOT / "数据")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "outputs/candidate_analysis_20261013")
    parser.add_argument("--history-json", type=Path)
    parser.add_argument("--runtime-manifest", type=Path)
    args = parser.parse_args()
    from dailyreport.events import parse_day
    from dailyreport.focus import focus_analysis

    baseline = read_baseline(args.baseline)
    history = load_history(args.data, args.history_json)
    by_day = dict(history)
    if any(node not in by_day for node in NODES):
        raise ValueError("逐日事件中缺少规定研判节点")
    source_manifest = raw_source_manifest(args.data.resolve(), history)
    products = dict(baseline)
    nodes = []
    for node in NODES:
        current_history = [(day, events) for day, events in history if parse_day(day) <= parse_day(node)]
        result = focus_analysis(current_history, node, by_day[node])
        name = f"日报/{node}/{node}日报.docx"
        products[name], docx_check = patch_docx(baseline[name], result["paragraphs"])
        nodes.append({"node": node, "docx": name, **docx_check,
                      "subject": result["subject"], "days": result["days"],
                      "subject_type": result.get("subject_type"),
                      "available_days": result.get("available_days", []),
                      "title": result.get("title"), "selection_score": result.get("selection_score"),
                      "phases": result["phases"], "comparisons": result["comparisons"],
                      "evidence": result["evidence"], "limitations": result["limitations"],
                      "history_last_day": current_history[-1][0],
                      "no_future_history": all(parse_day(day) <= parse_day(node)
                                               for day, _events in current_history)})
    unchanged = [name for name in expected_paths() if not name.endswith(".docx")]
    if len(unchanged) != 40 or any(products[name] != baseline[name] for name in unchanged):
        raise AssertionError("XLSX 或 PNG 与基线不一致")
    output = reserve_output(args.out)
    for name in expected_paths():
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(products[name])
    archive_path = output / "日报.zip"
    with ZipFile(archive_path, "w", ZIP_DEFLATED, compresslevel=9) as archive:
        for name in expected_paths():
            # Stable ZIP timestamps make the same algorithm inputs reproduce the hash.
            entry = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, products[name], compresslevel=9)
    with ZipFile(archive_path) as archive:
        if archive.namelist() != expected_paths() or archive.testzip() is not None:
            raise AssertionError("候选 ZIP 文件清单或 CRC 核验失败")
        if any(archive.read(name) != products[name] for name in expected_paths()):
            raise AssertionError("ZIP 内文件与候选成果不一致")
    runtime = {"python_executable": sys.executable, "renderer_status": "pending",
               "renderer_note": "尚未进行 DOCX 渲染与逐页图像检查，结构核验不代表版面核验通过"}
    if args.runtime_manifest:
        runtime["manifest_path"] = str(args.runtime_manifest.resolve())
        runtime["manifest"] = json.loads(args.runtime_manifest.read_text(encoding="utf-8"))
        dependencies = args.runtime_manifest.parent / "dependencies"
        runtime["dependency_resolution"] = "官方同版本缓存 runtime.json；当前会话未暴露 load_workspace_dependencies"
        runtime["bundled_node"] = str(dependencies / "node/bin/node")
        runtime["bundled_python"] = str(dependencies / "python/bin/python3.12")
        runtime["bundled_soffice_wrapper"] = str(dependencies / "bin/override/soffice")
        runtime["bundled_soffice"] = str(dependencies / "native/libreoffice-headless/libreoffice/LibreOfficeDev.app/Contents/MacOS/soffice")
    audit = {"schema_version": 1, "operation": "只替换第二节重点态势分析",
             "baseline": str(args.baseline.resolve()), "candidate": str(output.resolve()),
             "baseline_zip_sha256": sha256(args.baseline.read_bytes()) if args.baseline.is_file() else None,
             "candidate_zip_sha256": sha256(archive_path.read_bytes()),
             "checks": {"required_product_count": 48, "docx_count": 8,
                        "xlsx_count": 8, "png_count": 32, "unchanged_non_docx_count": 40,
                        "xlsx_and_png_byte_identical": True,
                        "all_docx_outside_section_xml_identical": True,
                        "all_docx_other_parts_identical": True,
                        "zip_contains_only_required_products": True,
                        "no_future_history": all(node["no_future_history"] for node in nodes)},
             "files": [{"path": name, "baseline_sha256": sha256(baseline[name]),
                        "candidate_sha256": sha256(products[name]),
                        "identical": products[name] == baseline[name]} for name in expected_paths()],
             "nodes": nodes, "source_files": source_manifest,
             "algorithm_files": [{"path": str(path.relative_to(REPO_ROOT)),
                                  "sha256": sha256(path.read_bytes())}
                                 for path in sorted((REPO_ROOT / "src/dailyreport").glob("*.py"))]
                                + [{"path": str(Path(__file__).relative_to(REPO_ROOT)),
                                    "sha256": sha256(Path(__file__).read_bytes())}],
             "history_snapshot": {"path": str(args.history_json.resolve()),
                                  "sha256": sha256(args.history_json.read_bytes())}
                                 if args.history_json else None,
             "runtime": runtime,
             "score_validation": {"official_score": None,
                                  "note": "未提交官方评测，不预测或保证分析分数"}}
    audit_path = output / "第二节对照核验.json"
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"candidate_dir": str(output.resolve()), "zip": str(archive_path.resolve()),
                      "audit": str(audit_path.resolve()), "checks": audit["checks"]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
