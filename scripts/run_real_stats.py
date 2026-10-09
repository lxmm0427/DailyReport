"""在真实数据上统计关联/判定分布（无标注，用于发现规则问题）。"""
import collections
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from dailyreport.link import adjudicate, link_day  # noqa: E402
from dailyreport.radar import load_day_radar  # noqa: E402
from dailyreport.textparse import load_day_texts  # noqa: E402

root = Path(sys.argv[1] if len(sys.argv) > 1 else "数据")
rows, unlinked = [], []
for d in sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: [int(x) for x in p.name.split(".")]):
    ms = load_day_texts(d)
    cands = [adjudicate(c) for c in link_day(load_day_radar(d), ms)]
    linked = {id(e.mention) for c in cands for e in c.evidence}
    unlinked += [(d.name, m) for m in ms if id(m) not in linked]
    for c in cands:
        rows.append(dict(day=d.name, kind=c.seg.kind, batch=c.seg.batch, verdict=c.verdict, region=c.region,
                         direction=c.direction, n_ev=len(c.evidence), srcs="+".join(sorted(c.sources)),
                         reasons=";".join(c.reasons), n_alts=c.seg.n_segs))
df = pd.DataFrame(rows)
df.to_pickle("/private/tmp/claude-501/-Users-lyr-research----2/214652a3-5762-4475-9103-aeba44da9591/scratchpad/verdicts.pkl")
pd.to_pickle(unlinked, "/private/tmp/claude-501/-Users-lyr-research----2/214652a3-5762-4475-9103-aeba44da9591/scratchpad/unlinked.pkl")
print(df.verdict.value_counts().to_dict())
print(pd.crosstab(df.verdict, df.direction))
print(df.srcs.value_counts().to_dict())
print("可信/天", df[df.verdict == "可信"].groupby("day").size().describe().round(1).to_dict())
c = collections.Counter(r.split(":")[1] for x in df.reasons for r in x.split(";") if ":" in r)
print("冲突字段", c.most_common())
print("未关联文本", len(unlinked), collections.Counter(m.source for _, m in unlinked),
      collections.Counter(m.direction for _, m in unlinked).most_common(5))
