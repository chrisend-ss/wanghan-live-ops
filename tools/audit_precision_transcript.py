"""Re-audit archived text without pretending to rerun audio or verify identities."""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.review_output import quality_status, write_transcripts
from app.speaker_verification import verify_speakers
from app.transcript_quality import audit_asr_quality


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--date", default="2026-09-29")
    parser.add_argument("--bvid", default="BV1xNas6ZEpB")
    args = parser.parse_args()
    if args.output.resolve() == args.input.parent.resolve():
        parser.error("Output must differ from the archived input directory")
    rows = [json.loads(line) for line in args.input.read_text(encoding="utf-8").splitlines() if line.strip()]
    speech = [r for r in rows if r.get("kind") == "speech"]
    for row in speech:
        row["legacy_speaker"] = row.get("speaker")
        row["legacy_speaker_cluster"] = row.get("speaker_cluster")
    audit = audit_asr_quality(rows)
    speaker = verify_speakers(speech)
    audit["verified_transcript"] = {"segment_count": 0, "speech_seconds": 0,
                                    "reason": "No new audio speaker verification in a legacy-text audit"}
    args.output.mkdir(parents=True, exist_ok=True)
    write_transcripts(args.output, rows, source="legacy_text_audit_precision_v2_1",
                      date=args.date, bvid=args.bvid, precision=True)
    report = {"run_mode": "legacy_text_audit", "pipeline_version": "precision_v2_1",
              "input": str(args.input), "audio_rerun": False, "asr_rerun": False,
              "speaker_verification_rerun": False, "speaker_verification": speaker,
              "quality": audit, "voiceprint_persisted": False,
              "generated_at": datetime.now(timezone.utc).isoformat()}
    (args.output/"quality_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    status = {"status": "audit_completed", "run_mode": "legacy_text_audit",
              **quality_status(audit, speaker)}
    (args.output/"status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(status, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

