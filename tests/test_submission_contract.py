from pathlib import Path

from build_submission import build_submission_for_date


def test_submission_contract_for_example_date():
    out_dir = build_submission_for_date('2025.5.1')
    assert (out_dir / '2025.5.1日报.docx').exists()
    assert (out_dir / '2025.5.1机舰活动明细.xlsx').exists()

    chart_dir = out_dir / '附件图表'
    expected = [
        '01_舰机侦巡数量曲线图.png',
        '02_中国主要机舰活动示意图.png',
        '03_美国主要机舰活动示意图.png',
        '04_其他国家主要机舰活动示意图.png',
    ]
    actual = sorted(p.name for p in chart_dir.iterdir() if p.is_file())
    assert actual == expected
