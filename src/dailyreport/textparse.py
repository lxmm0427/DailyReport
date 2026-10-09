"""开源军情 / 网上舆论 TXT 解析与要素抽取（规则 + 词典）。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from pathlib import Path

from . import lexicon as L

CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


@dataclass
class Mention:
    source: str                 # 军情 / 舆论
    day: str                    # 所在日期目录，如 2025.5.10
    file: str
    title: str
    body: str
    keywords: str = ""
    media: str | None = None
    country: str | None = None
    platform: str | None = None
    platforms: list[str] = field(default_factory=list)   # 编队等多平台
    kind: str | None = None     # air / ship
    count: int | None = None
    unit: str | None = None     # 架 / 艘
    start: str | None = None    # HHMM
    end: str | None = None
    region: str | None = None
    direction: str | None = None   # 东海/南海/黄海/其他
    relation: str | None = None    # 进入 / 离开 / 活动
    task: str | None = None
    event_date: str | None = None  # 正文中的日期 YYYY.M.D
    platform_raw: str | None = None
    kind_conflict: bool = False    # 平台名后接了另一类平台的类别词/量词（主体—平台错配）

    def to_dict(self) -> dict:
        return asdict(self)


def _num(s: str) -> int | None:
    if s.isdigit():
        return int(s)
    return CN_NUM.get(s)


def _field(text: str, name: str) -> str:
    m = re.search(rf"{name}：(.*)", text)
    return m.group(1).strip() if m else ""


_TIME = r"(\d{1,2})[时:：](\d{1,2})?分?"
_RANGE_PATTERNS = [
    re.compile(_TIME + r"\s*(?:起)?.{0,30}?(?:至|到|－|-|—|~)\s*" + _TIME),
]
_DATE = re.compile(r"(20\d\d)[年.](\d{1,2})[月.](\d{1,2})日?")


def _times(body: str) -> tuple[str | None, str | None]:
    # 只在包含“时”的片段中找“A时B分 … 至 C时D分”
    for m in re.finditer(r"(\d{1,2})时(\d{1,2})?分?", body):
        tail = body[m.end(): m.end() + 40]
        m2 = re.search(r"(?:至|到)\s*(\d{1,2})时(\d{1,2})?分?", tail)
        if m2:
            # 两个时间之间不能跨句
            if "。" in tail[: m2.start()]:
                continue
            s = f"{int(m.group(1)):02d}{int(m.group(2) or 0):02d}"
            e = f"{int(m2.group(1)):02d}{int(m2.group(2) or 0):02d}"
            return s, e
    return None, None


_RELATION_LEAVE = re.compile(r"离开|驶离|撤离|飞离|返航|结束.{0,6}后离|退出")
_RELATION_ENTER = re.compile(r"进入|驶入|飞入|抵达|进至|前出至")


def _first_sentence(body: str) -> str:
    return re.split(r"。", body, maxsplit=1)[0]


def extract(mention: Mention) -> Mention:
    title = mention.title
    m = re.search(r"据(.{1,20}?)(?:报道|消息|披露|发布)", mention.body)
    if m:
        mention.media = m.group(1)
    # 去掉“据XX报道”，避免媒体名中的国家被当作主体
    body = re.sub(r"据.{1,20}?(?:报道|消息|披露|发布)[，,]?", "", mention.body)
    fact = _first_sentence(body)
    # 事实部分：正文首句 + 第二句（第二句常带“随后离开”等），不含评论
    sents = [s for s in re.split(r"。", body) if s]
    fact2 = "。".join(sents[:2])

    m = _DATE.search(body)
    if m:
        mention.event_date = f"{int(m.group(1))}.{int(m.group(2))}.{int(m.group(3))}"
    else:
        m = re.search(r"(\d{1,2})月(\d{1,2})日", body)
        if m:
            mention.event_date = f"{mention.day.split('.')[0]}.{int(m.group(1))}.{int(m.group(2))}"

    # 平台：优先正文首句，其次标题
    plats = L.find_platforms(fact) or L.find_platforms(title) or L.find_platforms(body)
    # 国家：取首个平台之前最近的国家别名
    mention.country = _find_country(fact, title, mention.keywords)
    kind_hint = None
    if re.search(r"\d+架|[一两二三四]架|飞机|战机|机在", fact):
        kind_hint = "air"
    elif re.search(r"\d+艘|[一两二三四]艘|舰|潜艇|船", fact):
        kind_hint = "ship"
    if plats:
        resolved = []
        for _, _, cands in plats:
            p = L.resolve_platform(cands, mention.country, kind_hint)
            if p not in resolved:
                resolved.append(p)
        mention.platform = resolved[0]
        mention.platforms = resolved
        mention.kind = L.PLATFORM_KIND[mention.platform]
    else:
        mention.kind = kind_hint

    # 平台名后紧跟的类别词与平台类别不一致，如“P-8A“海神”导弹巡洋舰”
    if plats and mention.kind:
        nf = L._norm(fact)
        p0 = L.find_platforms(fact)
        if p0:
            tail = nf[p0[0][1]: p0[0][1] + 6]
            ship_word = re.match(r"(导弹|驱逐|护卫|巡洋|航空母|航母|潜艇|两栖|登陆|补给|巡逻舰|侦察船)", tail)
            air_word = re.match(r"(战斗机|轰炸机|预警机|侦察机|巡逻机|直升机|无人机|运输机|加油机|战机)", tail)
            if (mention.kind == "air" and ship_word) or (mention.kind == "ship" and air_word):
                mention.kind_conflict = True

    # 数量
    m = re.search(r"(\d+|[一两二三四五六七八九十])\s*(架次|架|艘次|艘)", fact)
    if m:
        mention.count = _num(m.group(1))
        mention.unit = "架" if "架" in m.group(2) else "艘"
        if mention.kind and (mention.unit == "架") != (mention.kind == "air"):
            mention.kind_conflict = True
    else:
        mention.count = 1
        mention.unit = "架" if mention.kind == "air" else "艘"

    mention.start, mention.end = _times(fact2)

    # 区域：首句内首个区域（排除“XX方向”里的方向词以外再找更具体的）
    regs = L.find_regions(fact) or L.find_regions(title)
    dir_m = re.search(r"(东海|南海|黄海)方向", fact) or re.search(r"(东海|南海|黄海)方向", title)
    if regs:
        # 若既有“东海方向”又有具体区域，取更具体者
        specific = [r for _, r in regs if r not in ("东海", "南海", "黄海")]
        mention.region = specific[0] if specific else regs[0][1]
    mention.direction = L.region_direction(mention.region) if mention.region else (dir_m.group(1) if dir_m else None)

    if _RELATION_LEAVE.search(fact2) or _RELATION_LEAVE.search(title):
        mention.relation = "离开"
    elif _RELATION_ENTER.search(fact2) or _RELATION_ENTER.search(title):
        mention.relation = "进入"
    else:
        mention.relation = "活动"

    mention.task = _find_task(_mask_platforms(fact2)) or _find_task(_mask_platforms(title))
    return mention


_TASK_RE = re.compile("|".join(re.escape(k) for k in sorted(L.TASK_ALIASES, key=len, reverse=True)))


def _mask_platforms(text: str) -> str:
    """把平台名替换为占位符，避免“反潜巡逻机”中的“反潜巡逻”被识别为任务。"""
    t = L._norm(text)
    return L._platform_regex().sub("〇", t)


def _find_task(text: str) -> str | None:
    m = _TASK_RE.search(text)
    return L.TASK_ALIASES[m.group(0)] if m else None


_COUNTRY_RE = re.compile("|".join(re.escape(k) for k in sorted(L.COUNTRY_ALIASES, key=len, reverse=True)))


def _find_country(*texts: str) -> str | None:
    for t in texts:
        for m in _COUNTRY_RE.finditer(t):
            k = m.group(0)
            if k in L.SINGLE_CHAR_COUNTRY:
                # 单字简称需后接军/海军/空军/方/舰/机等，且前面不是汉字词的一部分
                nxt = t[m.end(): m.end() + 2]
                prev = t[m.start() - 1: m.start()] if m.start() else ""
                if not re.match(r"[军海空方舰机]", nxt) or re.match(r"[一-龥]", prev or "x") and prev not in "，。、据称由与和及对在被":
                    continue
            return L.COUNTRY_ALIASES[k]
    return None


def parse_file(path: Path, source: str, day: str) -> Mention:
    text = path.read_text(encoding="utf-8")
    title = _field(text, "标题")
    body = _field(text, "正文")
    kw = _field(text, "主题词")
    return extract(Mention(source=source, day=day, file=path.name, title=title, body=body, keywords=kw))


def load_day_texts(day_dir: Path) -> list[Mention]:
    day = day_dir.name
    out = []
    for sub, src in (("开源军情", "军情"), ("网上舆论", "舆论")):
        for f in sorted((day_dir / sub).glob("*.txt")):
            out.append(parse_file(f, src, day))
    return out
