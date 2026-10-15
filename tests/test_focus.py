"""第二节研判的证据边界与可核验比较；不把关键词出现当作分析质量。"""
from dataclasses import replace
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dailyreport.events import Event, fmt_day  # noqa: E402
from dailyreport.focus import focus_analysis  # noqa: E402


def event(day, *, count=1, platform="RC-135V/W电子侦察机", kind="air",
          hull="", direction="东海", region=None, task="电子侦察",
          relation="活动", batch=None):
    return Event(
        day=f"2025.5.{day}", kind=kind, country="美国", platform=platform,
        batch=batch or f"{kind}-{day}-{platform}-{hull}", count=count,
        start="0800", end="1025", direction=direction,
        region=region or direction, task=task, base="同一基地", relation=relation,
        hull=hull, sources=["军情", "雷达"],
    )


def history(events, *, fill_gaps=True):
    by_day = {}
    for e in events:
        by_day.setdefault(e.day, []).append(e)
    if fill_gaps:
        first = min(e.date.toordinal() for e in events)
        last = max(e.date.toordinal() for e in events)
        for ordinal in range(first, last + 1):
            day = fmt_day(events[0].date.fromordinal(ordinal))
            by_day.setdefault(day, [])
    return sorted(by_day.items(), key=lambda item: tuple(map(int, item[0].split("."))))


def analyze(events, node_day=None):
    node_day = node_day or max(events, key=lambda e: e.date).day
    node_events = [e for e in events if e.day == node_day]
    return focus_analysis(history(events), node_day, node_events)


def metrics(phase):
    # 审计字段既可按阶段分组，也可置于阶段对象内；口径应相同。
    return phase.get("metrics", phase)


def body(result):
    return "\n".join(result["paragraphs"])


def changing_air():
    return [event(1), event(4), event(7, count=2), event(10, count=2)]


def test_history_is_sorted_deduplicated_and_future_is_excluded():
    evs = changing_air()
    future = event(13, count=99)
    h = [(evs[2].day, [evs[2]]), (future.day, [future]),
         (evs[0].day, [evs[0]]), (evs[3].day, [evs[3]]),
         (evs[1].day, [evs[1]]), (evs[1].day, [evs[1]])]
    result = focus_analysis(h, evs[-1].day, [evs[-1]])
    assert result["days"] == [e.day for e in evs]
    assert sum(metrics(p)["lead_count"] for p in result["phases"]) == 6
    assert "5月13日" not in body(result)


@pytest.mark.parametrize("n", [1, 2])
def test_fewer_than_three_evidence_days_do_not_invent_phases(n):
    result = analyze([event(day, count=day, relation="进入") for day in range(1, n + 1)])
    assert len(result["phases"]) <= 1
    assert not result["comparisons"]
    assert "第一阶段" not in body(result)
    assert "转为持续活动" not in body(result)


def test_observation_gaps_are_not_described_as_actual_interruptions():
    result = analyze(changing_air())
    text = body(result)
    assert "中断后恢复" not in text
    assert "实际活动中断" not in text or "不" in text
    assert result["limitations"]
    assert "三源核验" not in text  # 合成事件只包含两种来源。


def test_scale_doubles_while_observed_frequency_and_duration_stay_equal():
    result = analyze(changing_air())
    assert len(result["phases"]) == 2
    before, after = [metrics(p) for p in result["phases"]]
    assert (before["calendar_days"], after["calendar_days"]) == (4, 4)
    assert (before["evidence_days"], after["evidence_days"]) == (2, 2)
    assert (before["lead_records"], after["lead_records"]) == (2, 2)
    assert (before["lead_count"], after["lead_count"]) == (2, 4)
    assert (before["mean_batch_size"], after["mean_batch_size"]) == (1, 2)
    assert before["mean_duration_minutes"] == after["mean_duration_minutes"] == 145
    assert before["records_per_calendar_day"] == after["records_per_calendar_day"] == 0.5
    assert (before["lead_count_per_calendar_day"], after["lead_count_per_calendar_day"]) == (0.5, 1)
    comparison = result["comparisons"][0]
    assert comparison["deltas"]["lead_count"]["delta"] == 2
    assert comparison["deltas"]["lead_count"]["pct"] == 100
    assert comparison["deltas"]["records_per_calendar_day"]["delta"] == 0
    assert comparison["deltas"]["lead_count_per_calendar_day"]["delta"] == 0.5
    assert comparison["deltas"]["lead_count_per_calendar_day"]["pct"] == 100
    assert comparison["deltas"]["mean_duration_minutes"]["delta"] == 0


def test_unequal_windows_keep_calendar_denominators_for_comparison():
    # 前窗3天3条记录，后窗4天2条记录；累计架次3->4，但每日架次均为1。
    result = analyze([event(1), event(2), event(3), event(7, count=2), event(10, count=2)])
    assert len(result["phases"]) == 2
    before, after = [metrics(p) for p in result["phases"]]
    assert (before["calendar_days"], after["calendar_days"]) == (3, 4)
    assert (before["lead_count"], after["lead_count"]) == (3, 4)
    assert before["lead_count"] / before["calendar_days"] == after["lead_count"] / after["calendar_days"]
    assert before["lead_records"] / before["calendar_days"] > after["lead_records"] / after["calendar_days"]
    assert before["records_per_calendar_day"] == 1
    assert after["records_per_calendar_day"] == 0.5
    assert before["lead_count_per_calendar_day"] == after["lead_count_per_calendar_day"] == 1
    comparison = result["comparisons"][0]
    assert comparison["deltas"]["lead_count"]["pct"] == pytest.approx(100 / 3)
    assert comparison["deltas"]["records_per_calendar_day"]["delta"] == -0.5
    assert comparison["deltas"]["lead_count_per_calendar_day"]["delta"] == 0


def test_missing_input_days_do_not_become_zero_observations():
    es = changing_air()
    result = focus_analysis(history(es, fill_gaps=False), es[-1].day, [es[-1]])
    assert len(result["phases"]) == 2
    for p in result["phases"]:
        m = metrics(p)
        assert m["available_days"] == 2
        assert m["coverage_complete"] is False
        assert m["records_per_calendar_day"] is None
        assert m["lead_count_per_calendar_day"] is None
        assert m["evidence_day_ratio"] is None
        assert m["records_per_available_day"] == 1
    assert result["comparisons"][0]["deltas"]["records_per_calendar_day"]["delta"] is None
    assert result["comparisons"][0]["deltas"]["lead_count_per_calendar_day"]["delta"] is None


def test_comparisons_reference_only_actual_evidence():
    result = analyze(changing_air())
    evidence = {e["id"]: e for e in result["evidence"]}
    assert len(evidence) == 4
    assert all(e["day"] in result["days"] for e in evidence.values())
    assert all(e["sources"] == ["军情", "雷达"] for e in evidence.values())
    for p in result["phases"]:
        assert p["evidence_ids"]
        assert all(evidence[ref]["phase"] == p["index"] for ref in p["evidence_ids"])
        assert all(evidence[ref]["day"] in p["days"] for ref in p["evidence_ids"])
    for c in result["comparisons"]:
        assert c["evidence_ids"]
        assert set(c["evidence_ids"]) <= set(evidence)
        assert {evidence[ref]["phase"] for ref in c["evidence_ids"]} == {c["previous"], c["current"]}


def test_same_model_with_different_hulls_does_not_form_one_entity_thread():
    es = [event(d, kind="ship", platform="阿利·伯克级导弹驱逐舰", hull="DDG-51", task="巡逻")
          for d in (1, 3, 5)]
    es += [event(d, kind="ship", platform="阿利·伯克级导弹驱逐舰", hull="DDG-52", task="巡逻",
                 count=1 if d == 6 else 2) for d in (6, 8, 10)]
    result = analyze(es)
    assert result["days"] == ["2025.5.6", "2025.5.8", "2025.5.10"]


def test_same_identity_can_be_traced_across_directions():
    es = [event(d, kind="ship", platform="西奥多·罗斯福号航空母舰", hull="CVN-71",
                task="远海训练", direction="东海" if d < 7 else "南海")
          for d in (1, 4, 7, 10)]
    result = analyze(es)
    assert result["days"] == [e.day for e in es]
    assert "东海" in body(result) and "南海" in body(result)


def test_stage_members_use_only_stage_evidence():
    platform = "西奥多·罗斯福号航空母舰"
    escort = "阿利·伯克级导弹驱逐舰"
    es = []
    for d in (1, 4, 7, 10):
        lead = event(d, kind="ship", platform=platform, hull="CVN-71", task="远海训练",
                     region="东海" if d < 7 else "宁波外海")
        if d < 7:
            member = event(d, kind="ship", platform=escort, hull="DDG-51", task="远海训练")
            for e in (lead, member):
                e.formation = [lead.batch, member.batch]
                e.formation_lead = platform
                e.formation_order = [platform, escort]
            es.append(member)
        es.append(lead)
    result = analyze(es)
    assert len(result["phases"]) == 2
    # 最后阶段完全没有护航舰证据，不能套用全历史成员集合。
    last_phase = result["phases"][-1]
    assert escort not in str(last_phase)
    assert escort not in result["paragraphs"][-1]


def test_stable_observations_are_not_forced_into_change_phases():
    result = analyze([event(d) for d in (1, 4, 7, 10)])
    assert len(result["phases"]) <= 1
    assert not result["comparisons"]


def test_changed_thread_is_preferred_to_longer_but_stable_high_weight_platform():
    es = changing_air()
    es += [event(d, kind="ship", platform="西奥多·罗斯福号航空母舰", hull="CVN-71", task="远海训练")
           for d in range(1, 11)]
    result = analyze(es)
    assert "RC-135V/W" in str(result["subject"])


def test_missing_identity_support_does_not_create_cross_direction_transfer():
    es = [event(d, direction="东海" if d < 7 else "南海") for d in (1, 4, 7, 10)]
    # 同型与同基地不足以证明飞机个体转移。明确缺少个体身份时不描述跨海域同一实体转移。
    es = [replace(e, base="") for e in es]
    result = analyze(es)
    assert "活动重心由东海转向南海" not in body(result)
    assert "2025.5.1" not in result["days"]


@pytest.mark.parametrize("unknown_hull", [None, float("nan"), "nan", "未知", "不详", "—",
                                        "PROJECT-KDX-III", "T-AKE"])
def test_unknown_or_class_hull_values_do_not_establish_ship_identity(unknown_hull):
    es = [event(d, kind="ship", platform="阿利·伯克级导弹驱逐舰", hull=unknown_hull,
                task="巡逻", direction="东海" if d < 7 else "南海")
          for d in (1, 4, 7, 10)]
    result = analyze(es)
    assert "2025.5.1" not in result["days"]
    assert "2025.5.4" not in result["days"]


def test_repeated_enter_records_do_not_imply_transition_to_continuous_activity():
    result = analyze([replace(e, relation="进入") for e in changing_air()])
    assert result["phases"]  # 规模变化仍是可比较的，关系不应被改写。
    assert all(p["lead_relations"] == {"进入": 2} for p in result["phases"])
    assert "转为持续活动" not in body(result)
    assert "由进入到后续活动" not in body(result)


def test_minor_duration_drift_does_not_displace_supported_scale_change():
    es = changing_air()
    es += [replace(event(d, kind="ship", platform="西奥多·罗斯福号航空母舰", hull="CVN-71",
                         task="远海训练"), end=f"10{20 + d:02d}")
           for d in range(1, 11)]
    result = analyze(es)
    assert "RC-135V/W" in str(result["subject"])
