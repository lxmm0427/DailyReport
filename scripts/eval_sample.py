"""在官方样例(2025.10.20)上评估候选判定：按批号比对明细表。"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from dailyreport.link import adjudicate, link_day  # noqa: E402
from dailyreport.radar import load_day_radar  # noqa: E402
from dailyreport.textparse import load_day_texts  # noqa: E402

root = Path("提交示例文件")
day = sys.argv[1] if len(sys.argv) > 1 else "2025.10.20"
gt = pd.concat([pd.read_excel(root / f"日报/{day}/{day}机舰活动明细.xlsx", sheet_name=s).assign(sheet=s)
                for s in ("飞机", "舰艇")])
gtb = dict(zip(gt["批号"], gt["活动区域"]))
cands = [adjudicate(c) for c in link_day(load_day_radar(root / "数据" / day), load_day_texts(root / "数据" / day))]
pred = {c.seg.batch: c for c in cands if c.verdict == "可信"}
tp = set(pred) & set(gtb)
print(f"GT={len(gtb)} pred={len(pred)} TP={len(tp)} P={len(tp)/max(len(pred),1):.3f} R={len(tp)/len(gtb):.3f}")
reg_ok = sum(pred[b].region == gtb[b] for b in tp)
print(f"region acc on TP: {reg_ok}/{len(tp)}")
for b in tp:
    if pred[b].region != gtb[b]:
        print("  region", b, pred[b].region, "GT", gtb[b])
for c in cands:
    b = c.seg.batch
    if (b in gtb) != (c.verdict == "可信"):
        tag = "FN" if b in gtb else "FP"
        s = c.seg
        print(f"\n{tag} {s.kind} {b} {s.country}|{s.platform}|{c.region}|{s.task}|{s.start}-{s.end}|x{s.count} verdict={c.verdict} {c.reasons}")
        for e in c.evidence:
            m = e.mention
            print(f"   [{m.source}{m.file[:3]}] +{e.agree} -{e.conflict} :: {m.body[:90]}")
