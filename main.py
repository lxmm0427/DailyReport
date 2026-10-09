from pathlib import Path
import json

from src.competition_pipeline.pipeline import CompetitionPipeline


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent / "数据"
    pipeline = CompetitionPipeline(base_dir)
    summary = pipeline.run_for_date("2025.5.1")
    out_dir = Path(__file__).resolve().parent / "outputs"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "2025.5.1_summary.json"
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "date": summary["date"],
        "text_record_count": summary["text_record_count"],
        "radar_record_count": summary["radar_record_count"],
        "merged_event_count": summary["merged_event_count"],
        "sample_event": summary["events"][0] if summary["events"] else None,
    }, ensure_ascii=False, indent=2))
