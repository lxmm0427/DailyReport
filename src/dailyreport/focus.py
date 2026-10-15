"""Evidence-backed phase comparisons for section two; no remote model is required.

All counts describe verified records, rather than unobserved activity. A platform
class without an individual identifier is an activity series, not one aircraft
or ship. Missing dates never establish an actual interruption.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from itertools import combinations
from math import isclose
import re

from .events import Event, parse_day

CORE = {"东海", "南海", "黄海"}
ORDINALS = ("第一阶段", "第二阶段", "第三阶段")
METRICS = ("lead_count", "lead_count_per_calendar_day", "mean_batch_size", "mean_duration_minutes",
           "records_per_calendar_day", "evidence_day_ratio")


def _date(day: str, year: bool = False) -> str:
    d = parse_day(day)
    return f"{d.year}年{d.month}月{d.day}日" if year else f"{d.month}月{d.day}日"


def _join(items) -> str:
    values = list(dict.fromkeys(items))
    return "、".join(values[:-1]) + "和" + values[-1] if len(values) > 1 else "".join(values)


def _number(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _identity_value(value: str) -> str:
    value = str(value or "").strip()
    return "" if value.lower() in {"nan", "none", "null", "—", "-", "未知", "不详"} else value


def _strong_hull(value: str) -> bool:
    return bool(re.fullmatch(r"(?:[A-Z]{1,5}-)?\d{2,4}", _identity_value(value)))


def _label(e: Event) -> str:
    if _strong_hull(e.hull) and "级" in e.platform:
        return f"{e.platform}（舷号{e.hull}）"
    return e.platform


def _normalise(history, node: str) -> list[tuple[str, list[Event]]]:
    """Filter both container dates and event dates, merge dates, deduplicate batches."""
    result: dict[str, dict[str, Event]] = {}
    for day, events in history:
        if parse_day(day) > parse_day(node):
            continue
        rows = result.setdefault(day, {})
        for e in events:
            if e.day == day and e.date <= parse_day(node) and e.direction in CORE:
                previous = rows.get(e.batch)
                if previous is not None and previous != e:
                    raise ValueError(f"同日批号包含不一致的已核验事件：{day}/{e.batch}")
                rows[e.batch] = e
    return [(d, sorted(rows.values(), key=lambda e: (e.start, e.country, e.platform, e.batch)))
            for d, rows in sorted(result.items(), key=lambda item: parse_day(item[0]))]


@dataclass
class Thread:
    country: str
    key: str
    members: list[str]
    days: list[str]
    by_day: dict[str, list[Event]]
    score: float
    hull: str = ""
    base: str = ""
    direction: str = ""
    kind: str = ""
    named: bool = False
    task: str = ""
    identified: bool = False


def _is_lead(e: Event, t: Thread) -> bool:
    if (e.country, e.platform, e.kind) != (t.country, t.key, t.kind):
        return False
    if t.hull and _identity_value(e.hull) != t.hull:
        return False
    if not t.hull and _identity_value(e.hull):
        return False
    if t.named or t.identified:
        return True
    return (e.direction == t.direction and (not t.base or _identity_value(e.base) == t.base)
            and (not t.task or e.task == t.task))


def _leads(t: Thread, day: str) -> list[Event]:
    return [e for e in t.by_day[day] if _is_lead(e, t)]


def _duration(e: Event) -> float | None:
    try:
        if len(e.start) != 4 or len(e.end) != 4:
            return None
        if any(not (0 <= int(v[:2]) < 24 and 0 <= int(v[2:]) < 60) for v in (e.start, e.end)):
            return None
        start, end = e.minutes()
        return float(end - start) if end >= start else None
    except (ValueError, TypeError):
        return None


def _mean(values) -> float | None:
    values = list(values)
    return sum(values) / len(values) if values else None


def _state(t: Thread, day: str) -> dict:
    leads = _leads(t, day)
    return {
        "regions": tuple(sorted({e.region for e in leads})),
        "directions": tuple(sorted({e.direction for e in leads})),
        "tasks": tuple(sorted({e.task for e in leads})),
        "relations": tuple(sorted({e.relation for e in leads})),
        "members": tuple(sorted({_label(e) for e in t.by_day[day] if not _is_lead(e, t)})),
        "mean_batch_size": _mean(e.count for e in leads),
        "mean_duration_minutes": _mean(x for e in leads if (x := _duration(e)) is not None),
    }


def _change(a: dict, b: dict) -> float:
    score = sum(weight for field, weight in (("tasks", 4), ("regions", 3),
                                             ("directions", 4), ("members", 2))
                if a.get(field) != b.get(field))
    if not isclose(a.get("mean_batch_size") or 0, b.get("mean_batch_size") or 0):
        score += 3
    d0, d1 = a.get("mean_duration_minutes"), b.get("mean_duration_minutes")
    if (d0 is not None and d1 is not None and abs(d0 - d1) >= 30
            and abs(d0 - d1) >= 0.25 * max(d0, d1)):
        score += 1
    # Repeated 'enter' records alone do not demonstrate entering -> staying.
    if a.get("relations") != b.get("relations"):
        score += 2
    return score


def _phase_split(days: list[str], states: list[dict | str]) -> list[list[int]]:
    """Choose two or three chronological phases at supported changes, not by date count."""
    n = len(days)
    if n < 3:
        return []
    parsed = []
    for state in states:
        if isinstance(state, str):
            relation, region = state.split("|", 1)
            state = {"relations": (relation,), "regions": (region,)}
        parsed.append(state)
    boundaries = {i: _change(parsed[i - 1], parsed[i]) for i in range(1, n)}
    for i in boundaries:
        if (parse_day(days[i]) - parse_day(days[i - 1])).days >= 8:
            boundaries[i] += 2  # Evidence interval, never an actual interruption.
    valid = [i for i, value in boundaries.items() if value > 0]
    if not valid:
        return []
    # Include one evidence date of context around an endpoint transition, rather
    # than inventing an isolated one-day phase in an otherwise well-covered run.
    if n >= 4:
        for edge, contextual in ((1, 2), (n - 1, n - 2)):
            if boundaries[edge] > 0:
                boundaries[contextual] = max(boundaries[contextual], boundaries[edge] * 0.6)
        valid = [i for i, value in boundaries.items() if value > 0]
    best, best_score = [], float("-inf")
    for count in (1, 2):
        if count == 2 and (n < 5 or len(valid) < 2):
            continue
        for cuts in combinations(valid, count):
            bounds = (0, *cuts, n)
            phases = [list(range(a, b)) for a, b in zip(bounds, bounds[1:])]
            if n >= 4 and any(len(phase) < 2 for phase in phases):
                continue
            score = sum(boundaries[c] for c in cuts) - 3 * count
            score -= sum(2.5 for phase in phases if len(phase) == 1)
            # Prefer coherent phases; highly variable sequences remain explicitly described.
            score -= sum(_change(parsed[a], parsed[b]) * 0.2
                         for phase in phases for a, b in zip(phase, phase[1:]))
            score -= 0.05 * (max(map(len, phases)) - min(map(len, phases)))
            if score > best_score:
                best, best_score = phases, score
    return best


def find_threads(history: list[tuple[str, list[Event]]], node_events: list[Event]) -> list[Thread]:
    """Rank node-present, traceable activity series by coverage and supported changes."""
    from .analysis import importance  # Existing platform weights; no circular import at load time.

    if not node_events:
        return []
    node = max((e.day for e in node_events), key=parse_day)
    history = _normalise(history, node)
    today = next((events for day, events in history if day == node), [])
    node_events = [e for e in node_events if e.day == node and e.direction in CORE and e.foreign]
    anchors = {}
    for event in node_events:
        key = event.formation_lead or event.platform
        ref = next((e for e in today if e.country == event.country and e.platform == key
                    and (e.batch == event.batch or e.batch in event.formation)), None)
        if ref is None:
            continue
        named = "号" in ref.platform and "级" not in ref.platform
        hull, base = _identity_value(ref.hull), _identity_value(ref.base)
        individual = _strong_hull(hull) or named
        identity = (ref.country, ref.platform, ref.kind, hull,
                    "" if individual else base,
                    "" if individual else ref.direction,
                    "" if individual else ref.task)
        anchors[identity] = ref
    threads = []
    for ref in anchors.values():
        raw_hull = _identity_value(ref.hull)
        named = "号" in ref.platform and "级" not in ref.platform
        # Class/project codes such as PROJECT-... or a bare T-AKE are not
        # sufficient individual identities. Still retain their original field in evidence.
        strong_hull = _strong_hull(raw_hull)
        t = Thread(ref.country, ref.platform, [], [], {}, 0,
                   raw_hull, _identity_value(ref.base), ref.direction, ref.kind, named,
                   "" if strong_hull or named else ref.task, strong_hull)
        for day, events in history:
            leads = [e for e in events if _is_lead(e, t)]
            if not leads:
                continue
            batches = {e.batch for e in leads}
            batches.update(b for e in leads for b in e.formation)
            t.by_day[day] = [e for e in events if e.country == t.country and e.batch in batches]
        t.days = list(t.by_day)
        if len(t.days) < 3 or node not in t.by_day:
            continue
        states = [_state(t, d) for d in t.days]
        phase_indices = _phase_split(t.days, states)
        if not phase_indices:
            continue
        changes = [_change(a, b) for a, b in zip(states, states[1:])]
        changing_fields = sum(len({state[field] for state in states}) > 1
                              for field in ("tasks", "regions", "directions", "members", "mean_batch_size"))
        long_gaps = sum((parse_day(b) - parse_day(a)).days >= 8 for a, b in zip(t.days, t.days[1:]))
        task_coherence = sum(ref.task in state["tasks"] for state in states) / len(states)
        direction_coherence = sum(ref.direction in state["directions"] for state in states) / len(states)
        formation_support = sum(bool(state["members"]) for state in states) / len(states)
        heterogeneity = max(len({state["tasks"] for state in states}) - 2, 0)
        t.score = (1.5 * min(len(t.days), 12) + importance(ref) + 2 * changing_fields
                   + min(sum(changes), 8) + 8 * task_coherence + 4 * direction_coherence
                   + 4 * formation_support - 3 * heterogeneity - 1.5 * long_gaps
                   - 4 * sum(len(phase) == 1 for phase in phase_indices))
        t.members = list(dict.fromkeys(_label(e) for day in t.days for e in t.by_day[day]))
        threads.append(t)
    return sorted(threads, key=lambda t: (-t.score, t.country, t.key, t.hull, t.base, t.direction))


def _phase_metrics(t: Thread, days: list[str], available: set[str]) -> dict:
    leads = [e for day in days for e in _leads(t, day)]
    calendar_days = (parse_day(days[-1]) - parse_day(days[0])).days + 1
    available_days = sum(parse_day(days[0]) <= parse_day(day) <= parse_day(days[-1]) for day in available)
    complete = available_days == calendar_days
    return {
        "calendar_days": calendar_days, "available_days": available_days,
        "coverage_complete": complete, "evidence_days": len(days),
        "lead_records": len(leads), "lead_count": sum(e.count for e in leads),
        "lead_count_per_calendar_day": sum(e.count for e in leads) / calendar_days if complete else None,
        "mean_batch_size": _mean(e.count for e in leads),
        "mean_duration_minutes": _mean(x for e in leads if (x := _duration(e)) is not None),
        "records_per_calendar_day": len(leads) / calendar_days if complete else None,
        "evidence_day_ratio": len(days) / calendar_days if complete else None,
        "records_per_available_day": len(leads) / available_days if available_days else None,
    }


def _compare(previous: dict, current: dict) -> dict:
    deltas = {}
    for metric in METRICS:
        a, b = previous["metrics"][metric], current["metrics"][metric]
        delta = b - a if a is not None and b is not None else None
        deltas[metric] = {"previous": a, "current": b, "delta": delta,
                          "pct": delta / a * 100 if delta is not None and a else None}
    changes = {}
    for field in ("regions", "tasks", "members"):
        a, b = previous[field], current[field]
        changes[field] = {"added": [v for v in b if v not in a], "removed": [v for v in a if v not in b]}
    return {"previous": previous["index"], "current": current["index"],
            "deltas": deltas, "changes": changes,
            "evidence_ids": previous["evidence_ids"] + current["evidence_ids"]}


def _comparison_text(comparison: dict, previous: dict, current: dict, kind: str) -> str:
    p, c = previous["metrics"], current["metrics"]
    unit = "架次" if kind == "air" else "艘次"
    parts = []
    if p["calendar_days"] == c["calendar_days"]:
        count_text = (f"主平台记录量保持{c['lead_count']}{unit}" if c["lead_count"] == p["lead_count"] else
                      f"主平台记录量由{p['lead_count']}{'增至' if c['lead_count'] > p['lead_count'] else '减至'}{c['lead_count']}{unit}")
        parts.append(f"较前阶段，两个窗口均为{c['calendar_days']}个自然日，{count_text}")
        change = comparison["deltas"]["lead_count"]
        if change["pct"]:
            parts[-1] += f"（{'增加' if change['pct'] > 0 else '减少'}{_number(abs(change['pct']))}%）"
    else:
        parts.append(f"较前阶段，窗口由{p['calendar_days']}变为{c['calendar_days']}个自然日，按每日记录量比较")
        daily = comparison["deltas"]["lead_count_per_calendar_day"]
        if daily["delta"] is not None:
            if isclose(daily["delta"], 0):
                parts.append(f"按已加载日期折算，每日记录量均为{_number(daily['current'])}{unit}")
            else:
                parts.append(f"按已加载日期折算，每日记录量由{_number(daily['previous'])}变为{_number(daily['current'])}{unit}")
    batch = comparison["deltas"]["mean_batch_size"]
    batch_unit = "架" if kind == "air" else "艘"
    if batch["delta"] is not None and not isclose(batch["delta"], 0):
        parts.append(f"平均单批规模由{_number(batch['previous'])}{'增至' if batch['delta'] > 0 else '减至'}{_number(batch['current'])}{batch_unit}")
    else:
        parts.append(f"平均单批规模保持{_number(c['mean_batch_size'])}{batch_unit}")
    rate = comparison["deltas"]["records_per_calendar_day"]
    if rate["delta"] is None:
        parts.append("窗口内存在未加载日期，无法比较完整窗口的记录频率")
    elif isclose(rate["delta"], 0):
        parts.append(f"记录频率均为每日{_number(rate['current'])}批，保持一致")
    else:
        parts.append(f"已加载日期的记录频率由每日{_number(rate['previous'])}{'增至' if rate['delta'] > 0 else '减至'}{_number(rate['current'])}批")
    duration = comparison["deltas"]["mean_duration_minutes"]
    if duration["delta"] is not None:
        if isclose(duration["delta"], 0):
            parts.append(f"平均观测时段保持{_number(duration['current'])}分钟")
        else:
            parts.append(f"平均观测时段由{_number(duration['previous'])}变为{_number(duration['current'])}分钟")
    changed = False
    for field, name in (("regions", "主平台记录区域"), ("tasks", "主平台任务"), ("members", "关联平台")):
        change = comparison["changes"][field]
        if change["added"]:
            parts.append(f"{name}新增记录为{_join(change['added'])}")
            changed = True
        if change["removed"]:
            parts.append(f"前阶段的{name}{_join(change['removed'])}本阶段未再记录")
            changed = True
    if not changed:
        parts.append("区域、任务及关联平台构成一致")
    if batch["delta"] and rate["delta"] is not None and isclose(rate["delta"], 0):
        parts.append("单批规模变化，记录频率未变")
    return "；".join(parts) + "。"


def _phase_relation_text(relations: dict, leads: list[Event]) -> str:
    parts = [f"{relation}{n}条" for relation, n in relations.items()]
    first, last = leads[0], leads[-1]
    if len({e.day for e in leads}) > 1 and first.relation == "进入" and last.relation == "活动":
        parts.append("首末记录分别为进入和活动，支持后续活动线索")
    elif last.relation == "离开":
        parts.append("末次记录离开，仅指当次活动")
    return "、".join(parts)


def _overall(phases: list[dict], comparisons: list[dict], t: Thread) -> str:
    sizes = [p["metrics"]["mean_batch_size"] for p in phases]
    if all(isclose(a, b) for a, b in zip(sizes, sizes[1:])):
        size = "观测到的平均单批规模稳定"
    elif all(b >= a for a, b in zip(sizes, sizes[1:])):
        size = "观测到的平均单批规模上升"
    elif all(b <= a for a, b in zip(sizes, sizes[1:])):
        size = "观测到的平均单批规模下降"
    else:
        size = "观测到的平均单批规模有升有降"
    stable = []
    changing = []
    for field, name in (("regions", "区域"), ("tasks", "任务"), ("members", "关联平台构成")):
        (changing if any(c["changes"][field]["added"] or c["changes"][field]["removed"] for c in comparisons)
         else stable).append(name)
    text = [size]
    rates = [p["metrics"]["records_per_calendar_day"] for p in phases]
    if all(rate is not None for rate in rates):
        if all(isclose(a, b) for a, b in zip(rates, rates[1:])):
            text.append("按已加载日期折算的记录频率稳定")
        elif all(b >= a for a, b in zip(rates, rates[1:])):
            text.append("按已加载日期折算的记录频率上升")
        elif all(b <= a for a, b in zip(rates, rates[1:])):
            text.append("按已加载日期折算的记录频率下降")
        else:
            text.append("按已加载日期折算的记录频率有升有降")
    if stable:
        text.append(f"{_join(stable)}保持一致")
    if changing:
        text.append(f"{_join(changing)}有阶段差异")
    node_relations = {e.relation for e in _leads(t, t.days[-1])}
    text.append("节点当日主平台记录均为离开" if node_relations == {"离开"} else
                f"节点当日主平台记录关系为{_join(sorted(node_relations))}")
    return "；".join(text)


def focus_analysis(history: list[tuple[str, list[Event]]], node_day: str,
                   node_events: list[Event]) -> dict:
    """Return auditable facts, phase metrics, comparisons and evidence-limited prose."""
    history = _normalise(history, node_day)
    node_events = [e for e in node_events if e.day == node_day]
    threads = find_threads(history, node_events)
    result = {"node": node_day, "subject": None, "days": [], "phases": [],
              "evidence": [], "comparisons": [], "paragraphs": [], "limitations": [],
              "schema_version": 1, "available_days": [d for d, _ in history]}
    if not threads:
        result["paragraphs"] = ["节点当日相关可信活动尚不足以形成覆盖至少三个证据日期、具有阶段变化的重点主线；不据此编造持续、转移或中断趋势。"]
        return result
    t = threads[0]
    ref = _leads(t, node_day)[0]
    subject = t.country + _label(ref)
    indices = _phase_split(t.days, [_state(t, day) for day in t.days])
    available = set(result["available_days"])
    phases, evidence = [], []
    for i, idx in enumerate(indices, 1):
        days = [t.days[j] for j in idx]
        leads = [e for day in days for e in _leads(t, day)]
        member_sets = [{_label(e) for e in t.by_day[day] if not _is_lead(e, t)} for day in days]
        members = sorted(set.union(*member_sets))
        shared = sorted(set.intersection(*member_sets))
        ids = []
        for day in days:
            for e in t.by_day[day]:
                identifier = f"E{len(evidence) + 1:03d}"
                ids.append(identifier)
                evidence.append({"id": identifier, "phase": i, "day": day, "batch": e.batch,
                                 "lead": _is_lead(e, t), "country": e.country, "platform": e.platform,
                                 "hull": e.hull, "base": e.base, "direction": e.direction,
                                 "region": e.region, "task": e.task, "relation": e.relation,
                                 "count": e.count, "start": e.start, "end": e.end, "sources": e.sources})
        phases.append({"index": i, "days": days, "start": days[0], "end": days[-1],
                       "metrics": _phase_metrics(t, days, available),
                       "lead_relations": dict(Counter(e.relation for e in leads)),
                       "regions": sorted({e.region for e in leads}), "tasks": sorted({e.task for e in leads}),
                       "members": members, "shared_members": shared,
                       "optional_members": [p for p in members if p not in shared], "evidence_ids": ids})
    comparisons = [_compare(a, b) for a, b in zip(phases, phases[1:])]
    limitations = ["上述数量、频率和时段仅反映已加载材料的核验记录，不代表真实全量或连续在位。"]
    if _gaps(t.days):
        limitations.append("证据间隔不能证明实际活动中断、持续驻留或任务永久结束。")
    if not t.identified and not t.named:
        limitations.append("缺少个体标识，仅追踪同型活动序列，不认定同一机舰的连续航迹。")
    if any(not p["metrics"]["coverage_complete"] for p in phases):
        limitations.append("窗口内未加载日期不作零活动，完整频率不作比较。")
    if any(len(p["days"]) == 1 for p in phases):
        limitations.append("单证据日阶段样本有限，不外推长期趋势。")
    node_tasks = _join(dict.fromkeys(e.task for e in _leads(t, node_day)))
    paragraphs = [f"对{subject}的跨日活动分析。"
                  f"{_date(t.days[0], True)}至{_date(node_day)}，共{len(t.days)}个证据日期，节点任务为{node_tasks}。"
                  f"总体判断：{_overall(phases, comparisons, t)}（分析性判断）。"]
    for i, phase in enumerate(phases):
        days = phase["days"]
        leads = [e for day in days for e in _leads(t, day)]
        metrics = phase["metrics"]
        span = _date(days[0], True) + (f"至{_date(days[-1])}" if len(days) > 1 else "")
        unit = "架次" if t.kind == "air" else "艘次"
        text = (f"{ORDINALS[i]}（{span}）：主平台在{_join(phase['regions'])}执行{_join(phase['tasks'])}。"
                f"{metrics['calendar_days']}个自然日内，{metrics['evidence_days']}日有记录，"
                f"共{metrics['lead_records']}批、{metrics['lead_count']}{unit}；"
                f"记录关系为{_phase_relation_text(phase['lead_relations'], leads)}。")
        if phase["shared_members"]:
            text += f"各证据日均有关联平台{_join(phase['shared_members'])}。"
        if phase["optional_members"]:
            text += f"部分证据日另有关联平台{_join(phase['optional_members'])}。"
        if i:
            interval = (parse_day(days[0]) - parse_day(phases[i - 1]["end"])).days
            if interval > 1:
                text += f"距前阶段末次证据{interval}日，不据此判断实际中断。"
            text += _comparison_text(comparisons[i - 1], phases[i - 1], phase, t.kind)
        paragraphs.append(text)
    last = phases[-1]["metrics"]
    relation = {e.relation for e in _leads(t, node_day)}
    question = "是否再次出现相关记录" if "离开" in relation else "是否继续出现相关记录或转为离开"
    paragraphs.append(f"后续验证：关注{question}，平均单批规模是否维持"
                      f"{_number(last['mean_batch_size'])}{'架' if t.kind == 'air' else '艘'}、区域及任务构成是否变化。"
                      + "".join(limitations))
    result.update(subject=subject, days=t.days, phases=phases, evidence=evidence,
                  comparisons=comparisons, paragraphs=paragraphs, limitations=limitations,
                  title=t.country + t.key, selection_score=t.score,
                  subject_type="entity" if t.identified or t.named else "activity_series")
    return result


def section_focus(history, node_day, node_events):
    result = focus_analysis(history, node_day, node_events)
    return result["paragraphs"], result.get("title")


def _gaps(days: list[str]) -> list[tuple[str, str]]:
    return [(a, b) for a, b in zip(days, days[1:]) if (parse_day(b) - parse_day(a)).days > 1]


def _day_relation(events: list[Event]) -> str:
    return _join(sorted({e.relation for e in events}))


def _trend_word(s0: str, s1: str) -> str:
    """Compatibility helper with conservative wording, including singleton enter records."""
    r0, g0 = s0.split("|", 1)
    r1, g1 = s1.split("|", 1)
    if g0 != g1:
        return f"记录区域由{g0}变为{g1}"
    if r1 == "离开":
        return "末次记录为离开，仅支持当次离开状态"
    if r0 == "进入" and r1 == "活动":
        return "首末记录分别为进入和活动"
    return f"首末记录关系均为{r1}" if r0 == r1 else f"记录关系由{r0}变为{r1}"
