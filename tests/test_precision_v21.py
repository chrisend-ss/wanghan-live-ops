import copy
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from app.precision_audio import AudioZone, assign_speakers, build_precision_transcript
from app.review_output import quality_status, write_transcripts
from app.speaker_verification import classify_scores, verify_speakers
from app.transcript_quality import audit_asr_quality, verified_wanghan


def speech(text="今天排完就休息了", start=0, duration=4, **values):
    return {"kind": "speech", "text": text, "start_seconds": start,
            "end_seconds": start + duration, "avg_logprob": -0.25,
            "no_speech_prob": 0.05, "compression_ratio": 1.2, **values}


class ASRTests(unittest.TestCase):
    def test_named_hallucinations_and_new_subtitle_credit(self):
        texts = ["请不吝点赞 订阅 转发 打赏支持明镜与点点栏目",
                 "中文字幕志愿者 李宗盛", "YoYo Television Series Exclusive",
                 "字幕校对 新名字", "明镜需要您的支持 欢迎收看订阅明镜"]
        rows = [speech(text, i * 70, duration=15) for i, text in enumerate(texts)]
        result = audit_asr_quality(rows)
        self.assertEqual(result["hallucination_audit"]["distribution"]["rejected"], 5)
        self.assertTrue(all(not r["asr_quality_pass"] for r in rows))

    def test_novel_distant_repeat_and_template(self):
        repeated = "这是从没有列入词库的一条很长而固定的伪造转写内容"
        rows = [speech(repeated, start) for start in (0, 70, 140)]
        result = audit_asr_quality(rows)
        self.assertEqual(result["hallucination_audit"]["distribution"]["review"], 3)
        self.assertTrue(all("distant_exact_repeat" in r["hallucination_reasons"] for r in rows))
        rows = [speech("这是全新出现的固定版权内容其长度足够长" + tail, start)
                for tail, start in (("甲", 0), ("乙", 70), ("丙", 140))]
        audit_asr_quality(rows)
        self.assertTrue(all("distant_recurring_template" in r["hallucination_reasons"] for r in rows))

    def test_live_repeated_short_commands_remain_clear(self):
        rows = [speech("来宝宝跑车", start) for start in (0, 70, 140, 210)]
        audit_asr_quality(rows)
        self.assertTrue(all(r["asr_quality_pass"] for r in rows))
        self.assertTrue(all(not r["hallucination_detected"] for r in rows))

    def test_bad_model_evidence_and_missing_metrics_fail(self):
        rows = [speech(no_speech_prob=0.85), speech(avg_logprob=-1.4),
                speech(avg_logprob=None), speech(no_speech_prob=float("nan"))]
        audit_asr_quality(rows)
        self.assertTrue(all(not r["asr_quality_pass"] for r in rows))

    def test_repetition_with_anomaly_rejected(self):
        rows = [speech("我爱你" * 8, duration=20, no_speech_prob=0.8)]
        audit_asr_quality(rows)
        self.assertEqual(rows[0]["hallucination_status"], "rejected")

    def test_asr_independent_of_identity_and_preserves_raw_text(self):
        original = speech("嗯 今天排完就休息了", speaker_confidence="high")
        rows = [copy.deepcopy(original), {**original, "speaker_confidence": "low"}]
        audit_asr_quality(rows)
        self.assertEqual(rows[0]["asr_quality_score"], rows[1]["asr_quality_score"])
        self.assertEqual(rows[0]["text"], original["text"])


class SpeakerTests(unittest.TestCase):
    def verify(self, rows, embedding, **kwargs):
        return verify_speakers(rows, ranges=[[10, 14], [20, 24]],
            reference_confirmed=True, zones=[AudioZone("speech", 0, 1000)],
            embedding=embedding, **kwargs)

    def test_three_classes_and_short_segments(self):
        rows = [speech(start=x, duration=d) for x, d in ((30, 4), (40, 4), (50, 4), (60, .6))]
        vectors = {30: [1, 0], 40: [0, 1], 50: [.6, .8]}
        result = self.verify(rows, lambda s, e: vectors.get(int(s), [1, 0]))
        self.assertEqual(result["distribution"], {"wanghan": 1, "non_wanghan": 1, "uncertain": 2})
        self.assertTrue(rows[0]["speaker_verification_pass"])
        self.assertFalse(result["voiceprint_persisted"])
        self.assertEqual(result["duration_seconds"]["uncertain"], 4.6)

    def test_missing_reference_does_not_load_model_or_infer_dominant(self):
        rows = [speech()]
        with patch("app.precision_audio._speaker_encoder") as encoder:
            result = assign_speakers(Path("unused.wav"), rows)
        encoder.assert_not_called()
        self.assertEqual(rows[0]["speaker_verification"], "uncertain")
        self.assertFalse(result["speaker_summary"]["reference_usable"])

    def test_mixed_reference_fails_closed(self):
        rows = [speech(start=30)]
        result = self.verify(rows, lambda s, e: [1, 0] if s < 20 else [0, 1])
        self.assertEqual(result["reference_status"], "reference_inconsistent_or_mixed")
        self.assertEqual(rows[0]["speaker_verification"], "uncertain")

    def test_reference_crossing_music_fails(self):
        rows = [speech(start=30)]
        result = verify_speakers(rows, ranges=[[10,14], [20,24]], reference_confirmed=True,
            zones=[AudioZone("speech", 10,12), AudioZone("music", 12,14), AudioZone("speech",20,24)],
            embedding=lambda s,e: np.array([1,0]))
        self.assertEqual(result["reference_status"], "reference_not_clean_speech")

    def test_overlapping_references_are_not_independent(self):
        rows = [speech(start=30)]
        result = verify_speakers(rows, ranges=[[10,14], [12,16]], reference_confirmed=True,
            zones=[AudioZone("speech", 0,100)], embedding=lambda s,e:[1,0])
        self.assertEqual(result["reference_status"], "need_two_independent_nonoverlapping_references")

    def test_old_polluted_long_reference_is_rejected(self):
        rows = [speech(start=30)]
        result = verify_speakers(rows, ranges=[[2823,2875], [2952,2990]], reference_confirmed=True)
        self.assertEqual(result["reference_status"], "reference_must_be_3_to_12_seconds")

    def test_speaker_change_inside_one_segment_is_uncertain(self):
        rows = [speech(start=30, duration=8)]
        self.verify(rows, lambda s,e:[0,1] if s == 34 else [1,0])
        self.assertEqual(rows[0]["speaker_verification"], "uncertain")

    def test_embedding_failure_and_nan_are_uncertain(self):
        rows = [speech(start=30)]
        self.verify(rows, lambda s,e:[float("nan"),0] if s==30 else [1,0])
        self.assertEqual(rows[0]["speaker_verification_reason"], "embedding_failed")

    def test_thresholds_and_boundary(self):
        with self.assertRaises(ValueError):
            classify_scores([.8], verify=.5, reject=.7)
        self.assertEqual(classify_scores([.72], verify=.72, reject=.45), "wanghan")
        self.assertEqual(classify_scores([.45], verify=.72, reject=.45), "non_wanghan")
        self.assertEqual(classify_scores([.9,.1], verify=.72, reject=.45), "uncertain")


class OutputTests(unittest.TestCase):
    def load_cloud_runner(self, result=None, error=None):
        bili = types.ModuleType("app.bilibili")
        bili.extract_bvid = lambda url: "BV1xNas6ZEpB"
        browser = types.ModuleType("app.bilibili_browser")
        def transcribe(**kwargs):
            if error:
                raise error
            return result
        browser.transcribe_page_media = transcribe
        path = Path(__file__).resolve().parents[1]/"tools/cloud_bilibili_review.py"
        spec = importlib.util.spec_from_file_location("cloud_test", path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"app.bilibili":bili, "app.bilibili_browser":browser}):
            spec.loader.exec_module(module)
        return module

    def test_cloud_runner_writes_gated_outputs_and_quality_status(self):
        row = speech("王焓干净句子", speaker="王焓", speaker_verification="wanghan",
                     speaker_verification_pass=True, asr_quality_pass=True, hallucination_status="clear")
        summary = {"reference_usable":True, "distribution":{"wanghan":1,"non_wanghan":0,"uncertain":0}}
        quality = {"verified_transcript":{"segment_count":1}, "hallucination_audit":{"distribution":{"clear":1}}}
        result = {"info":{"bvid":"BV1xNas6ZEpB"}, "source":"test_precision_v2_1",
                  "segments":[row], "speaker_summary":summary, "quality":quality, "zones":[]}
        module = self.load_cloud_runner(result)
        with tempfile.TemporaryDirectory() as tmp, contextlib.chdir(tmp):
            request = Path(tmp)/"request.json"
            request.write_text(json.dumps({"url":"BV1xNas6ZEpB", "date":"2026-09-29",
                "precision_mode":True, "output_suffix":"precise_v2_1"}), encoding="utf-8")
            with patch.object(sys,"argv",["cloud","--request",str(request)]), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(module.main(),0)
            out = Path("reviews/2026-09-29_BV1xNas6ZEpB_precise_v2_1")
            self.assertIn(row["text"], (out/"wanghan_verified_transcript.md").read_text(encoding="utf-8"))
            status = json.loads((out/"status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["status"],"completed")
            self.assertEqual(status["quality_status"],"needs_human_text_review")
            report = json.loads((out/"quality_report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["speaker_verification"], summary)

    def test_cloud_error_status_is_not_completed(self):
        module = self.load_cloud_runner(error=RuntimeError("audio unavailable"))
        with tempfile.TemporaryDirectory() as tmp, contextlib.chdir(tmp):
            request = Path(tmp)/"request.json"
            request.write_text(json.dumps({"url":"BV1xNas6ZEpB", "date":"2026-09-29",
                                          "precision_mode":True}), encoding="utf-8")
            with patch.object(sys,"argv",["cloud","--request",str(request)]), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(module.main(),1)
            status = json.loads(Path("reviews/2026-09-29_BV1xNas6ZEpB/status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["status"],"failed")
            self.assertEqual(status["error"],"audio unavailable")

    def test_triple_gate_and_full_evidence_output(self):
        base = speech("保留这句王焓口播", speaker_verification="wanghan", speaker_verification_pass=True,
                      asr_quality_pass=True, hallucination_status="clear")
        rows = [base, {**base,"text":"不确定","speaker_verification":"uncertain"},
                {**base,"text":"质量不通过","asr_quality_pass":False},
                {**base,"text":"幻觉待复核","hallucination_status":"review"},
                {**base,"text":"歌词","kind":"music"}]
        self.assertEqual(verified_wanghan(rows), [base])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            write_transcripts(path, rows, source="test", date="test", bvid="BVtest", precision=True)
            verified = (path/"wanghan_verified_transcript.md").read_text(encoding="utf-8")
            self.assertIn(base["text"], verified)
            self.assertNotIn("质量不通过", verified)
            self.assertNotIn("歌词", verified)
            decoded = [json.loads(line) for line in (path/"transcript.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(decoded), 5)
            self.assertEqual(decoded[0]["speaker_verification"], "wanghan")

    def test_empty_verified_file_and_status_are_honest(self):
        status = quality_status({}, {"reference_usable":False})
        self.assertEqual(status["quality_status"], "reference_required")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            write_transcripts(path, [], source="test", date="test", bvid="BVtest", precision=True)
            self.assertIn("没有片段", (path/"wanghan_verified_transcript.md").read_text(encoding="utf-8"))

    def test_end_to_end_pipeline_contract_with_mock_audio_models(self):
        rows = [speech("干净口播第一句", start=30),
                speech("中文字幕志愿者 李宗盛", start=40)]
        with patch("app.precision_audio.segment_speech_music", return_value=[AudioZone("speech",0,100)]), \
             patch("app.precision_audio.transcribe_speech_zones", return_value=rows):
            result = build_precision_transcript(Path("unused.wav"))
        self.assertEqual(result["quality"]["pipeline_version"], "precision_v2_1")
        self.assertEqual(result["speaker_summary"]["distribution"]["uncertain"], 2)
        self.assertEqual(result["quality"]["hallucination_audit"]["distribution"]["rejected"], 1)
        self.assertEqual(result["quality"]["verified_transcript"]["segment_count"], 0)

    def test_existing_bv_fixed_hallucinations_all_excluded(self):
        path = Path(__file__).resolve().parents[1]/"reviews/2026-09-29_BV1xNas6ZEpB_precise_v2/transcript.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        audit_asr_quality(rows)
        named = [r for r in rows if any(s in r.get("text","") for s in ("中文字幕志愿者", "明镜", "YoYo Television Series Exclusive"))]
        self.assertGreater(len(named), 0)
        self.assertTrue(all(not r["asr_quality_pass"] for r in named))


if __name__ == "__main__":
    unittest.main()
