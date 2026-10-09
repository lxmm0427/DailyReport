from pathlib import Path

from src.competition_pipeline.pipeline import CompetitionPipeline, EventRecord


def test_merge_text_and_radar_creates_single_event():
    pipeline = CompetitionPipeline(Path('/tmp'))
    text_event = EventRecord(
        date='2025.5.1',
        source='开源军情',
        title='中国054B型导弹护卫舰在南海任务海域持续开展既定行动',
        platform='054B型导弹护卫舰',
        task='反潜巡逻',
        region='南海',
        action='活动',
        raw_text='test',
        confidence=0.7,
    )
    radar_event = EventRecord(
        date='2025.5.1',
        source='雷达',
        title='雷达记录: 054B',
        platform='054B',
        task='反潜巡逻',
        region='南海',
        action='活动',
        raw_text='test',
        confidence=0.85,
    )

    merged = pipeline._merge_text_and_radar([text_event], [radar_event])

    assert len(merged) == 1
    assert merged[0].source in {'开源军情', '雷达'}
    assert merged[0].platform in {'054B型导弹护卫舰', '054B'}


def test_filter_credible_events_requires_multi_source_support():
    pipeline = CompetitionPipeline(Path('/tmp'))
    single_source = EventRecord(
        date='2025.5.1',
        source='开源军情',
        title='测试事件',
        platform='P-8A',
        task='侦察',
        region='东海',
        action='活动',
        raw_text='test',
        confidence=0.8,
    )
    multi_source = EventRecord(
        date='2025.5.1',
        source='网上舆论',
        title='测试事件',
        platform='P-8A',
        task='侦察',
        region='东海',
        action='活动',
        raw_text='test',
        confidence=0.75,
    )

    all_events = [single_source, multi_source]
    credible = pipeline._filter_credible_events(all_events)

    assert len(credible) == 1
    assert credible[0].platform == 'P-8A'


def test_filter_rejects_conflicting_actions_even_with_two_sources():
    pipeline = CompetitionPipeline(Path('/tmp'))
    enter_event = EventRecord(
        date='2025.5.1',
        source='开源军情',
        title='进入南海',
        platform='054B',
        task='反潜巡逻',
        region='南海',
        action='进入',
        raw_text='test',
        confidence=0.8,
    )
    leave_event = EventRecord(
        date='2025.5.1',
        source='雷达',
        title='离开南海',
        platform='054B',
        task='反潜巡逻',
        region='南海',
        action='离开',
        raw_text='test',
        confidence=0.9,
    )

    assert pipeline._filter_credible_events([enter_event, leave_event]) == []


def test_merge_prefers_region_from_text_when_radar_lacks_location():
    pipeline = CompetitionPipeline(Path('/tmp'))
    text_event = EventRecord(
        date='2025.5.1',
        source='开源军情',
        title='中国舰艇在南海持续活动',
        platform='054B',
        task='反潜巡逻',
        region='南海',
        action='活动',
        raw_text='南海持续活动',
        confidence=0.72,
    )
    radar_event = EventRecord(
        date='2025.5.1',
        source='雷达',
        title='雷达记录: 054B',
        platform='054B',
        task='反潜巡逻',
        region='未知区域',
        action='活动',
        raw_text='{"国家地区": "中国"}',
        confidence=0.9,
    )

    merged = pipeline._merge_text_and_radar([text_event], [radar_event])

    assert len(merged) == 1
    assert merged[0].region == '南海'
    assert '雷达' in merged[0].source_set
    assert '开源军情' in merged[0].source_set
