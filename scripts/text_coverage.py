"""统计文本抽取覆盖率，并抽样打印缺失字段的文本。"""
import random
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from dailyreport.textparse import load_day_texts  # noqa: E402

root = Path(sys.argv[1] if len(sys.argv) > 1 else "数据")
rows = []
for d in sorted(p for p in root.iterdir() if p.is_dir()):
    rows += [m.to_dict() for m in load_day_texts(d)]
df = pd.DataFrame(rows)
df.to_pickle("/private/tmp/claude-501/-Users-lyr-research----2/214652a3-5762-4475-9103-aeba44da9591/scratchpad/mentions_" + ("sample" if "示例" in str(root) else "real") + ".pkl")
print("total", len(df))
for c in ["country", "platform", "start", "region", "direction", "task", "media", "event_date"]:
    print(f"{c:12s}", df.groupby("source")[c].apply(lambda s: f"{s.notna().mean():.3f}").to_dict())
field = sys.argv[2] if len(sys.argv) > 2 else None
if field:
    miss = df[df[field].isna()]
    random.seed(0)
    for i in random.sample(range(len(miss)), min(12, len(miss))):
        r = miss.iloc[i]
        print("---", r.source, r.file); print(r.title); print(r.body)
