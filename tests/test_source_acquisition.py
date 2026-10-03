import importlib.util
import json
import tempfile
import unittest
import sys
import types
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "sources", ROOT / "skills/wanghan-core-ops/scripts/prepare_sources.py")
sources = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sources)
sys.path.insert(0, str(ROOT))


class ExistingBilibiliTests(unittest.TestCase):
    def test_public_import_uses_selected_page(self):
        from app import bilibili
        payload = {"data": {"title": "example", "pages": [
            {"cid": 11, "duration": 50}, {"cid": 22, "duration": 80}]}}
        with patch.object(bilibili, "_get_json", return_value=payload):
            info = bilibili.get_video_info("https://www.bilibili.com/video/BV1TPaf6tEJi?p=2")
            self.assertEqual((info["part"], info["cid"], info["duration"]), (2, 22, 80))
            with self.assertRaises(ValueError):
                bilibili.get_video_info("https://www.bilibili.com/video/BV1TPaf6tEJi?p=3")

    def test_public_subtitles_do_not_confirm_identity(self):
        from app import bilibili
        responses = [{"data": {"subtitle": {"subtitles": [
            {"lan": "zh", "subtitle_url": "https://example.invalid/subtitle"}]}}},
            {"body": [{"from": 1, "to": 2, "content": "原始文字"}]}]
        with patch.object(bilibili, "_get_json", side_effect=responses):
            rows = bilibili.get_public_subtitles("BV1TPaf6tEJi", 1)
        self.assertEqual(rows[0]["speaker"], "说话人_未区分")
        self.assertEqual(rows[0]["text"], "原始文字")

    def test_browser_metadata_uses_selected_page(self):
        # Audio inference dependencies are unrelated to page metadata selection.
        fake_audio = types.ModuleType("app.precision_audio")
        fake_audio.build_precision_transcript = None
        fake_audio.convert_to_analysis_wav = None
        with patch.dict(sys.modules, {"app.precision_audio": fake_audio}):
            from app.bilibili_browser import _metadata_from_initial
        initial = {"videoData": {"cid": 11, "duration": 130, "pages": [
            {"cid": 11, "duration": 50}, {"cid": 22, "duration": 80}]}}
        info = _metadata_from_initial(initial, "BV1TPaf6tEJi", 2)
        self.assertEqual((info["part"], info["cid"], info["duration"]), (2, 22, 80))
        with self.assertRaises(ValueError):
            _metadata_from_initial({}, "BV1TPaf6tEJi", 2)


class SourceAcquisitionTests(unittest.TestCase):
    def test_bilibili_identity_keeps_part_drops_tracking(self):
        self.assertEqual(sources.recording_identity(
            "https://www.bilibili.com/video/BV1TPaf6tEJi/?p=2&token=secret#x"),
            {"bvid": "BV1TPaf6tEJi", "part": 2,
             "url": "https://www.bilibili.com/video/BV1TPaf6tEJi/?p=2"})
        self.assertEqual(sources.recording_identity("BV1TPaf6tEJi")["part"], 1)

    def test_bad_host_and_part_fail(self):
        for url in ["https://evil.example/video/BV1TPaf6tEJi",
                    "https://www.bilibili.com/video/BV1TPaf6tEJi?p=0",
                    "https://www.bilibili.com/video/BV1TPaf6tEJi?p=1&p=2"]:
            with self.assertRaises(ValueError):
                sources.recording_identity(url)

    def test_probe_selects_exact_cid_and_part_duration(self):
        metadata = {"data": {"title": "example", "pubdate": 10,
                             "pages": [{"cid": 1, "duration": 20},
                                       {"cid": 2, "duration": 30}]}}
        with patch.object(sources, "public_json", side_effect=[metadata, {"data": {}}]):
            r = sources.probe_bilibili("https://www.bilibili.com/video/BV1TPaf6tEJi?p=2")
        self.assertEqual((r["cid"], r["duration_seconds"]), (2, 30))
        self.assertIsNone(r["live_date"])
        self.assertEqual(r["subtitle_status"], "not_available_anonymously")

    def test_failure_does_not_serialize_signed_url(self):
        with patch.object(sources, "public_json", side_effect=ValueError("token=secret")):
            r = sources.probe_bilibili("BV1TPaf6tEJi")
        self.assertEqual(r["status"], "metadata_unavailable")
        self.assertNotIn("secret", json.dumps(r))

    def test_browser_metadata_is_accepted_without_network_or_subtitle_claim(self):
        observed = {"bvid": "BV1TPaf6tEJi", "title": "observed", "pages": [
            {"cid": 2, "duration": 30}]}
        with patch.object(sources, "public_json", side_effect=AssertionError("no network")):
            r = sources.probe_bilibili("BV1TPaf6tEJi", observed)
        self.assertEqual(r["status"], "metadata_available")
        self.assertEqual(r["metadata_source"], "browser_observed")
        self.assertEqual(r["subtitle_status"], "not_checked")
        observed["bvid"] = "BV0000000000"
        self.assertEqual(sources.probe_bilibili("BV1TPaf6tEJi", observed)["status"],
                         "metadata_unavailable")

    def test_review_reuse_requires_cid_and_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "example_BV1TPaf6tEJi"
            folder.mkdir()
            (folder / "status.json").write_text('{"status":"completed"}')
            (folder / "metadata.json").write_text('{"bvid":"BV1TPaf6tEJi","cid":2}')
            for name in ["transcript.jsonl", "quality_report.json", "audio_zones.jsonl"]:
                (folder / name).write_text('{}\n')
            identity = sources.recording_identity("BV1TPaf6tEJi")
            self.assertFalse(sources.find_reviews(Path(tmp), identity, 1)[0]["reuse_candidate"])
            self.assertFalse(sources.find_reviews(Path(tmp), identity)[0]["reuse_candidate"])
            self.assertTrue(sources.find_reviews(Path(tmp), identity, 2)[0]["reuse_candidate"])
            (folder / "quality_report.json").unlink()
            self.assertFalse(sources.find_reviews(Path(tmp), identity, 2)[0]["reuse_candidate"])

    def capture(self, value=0, unit="count"):
        return {"source_url": "https://example.douyin.com/review?token=secret#auth",
                "captured_at": "2026-10-03T12:00:00+08:00", "session_id": "example",
                "Cookie": "never-save", "metrics": [{"key": "entries", "label": "进房",
                "value": value, "unit": unit, "kind": "window_increment"}]}

    def test_normalizer_keeps_missing_and_zero_distinct(self):
        r = sources.normalize_capture(self.capture(0))
        self.assertEqual(r["metrics"][0]["value"], 0)
        self.assertNotIn("entries", r["missing_target_fields"])
        r = sources.normalize_capture(self.capture("--"))
        self.assertIsNone(r["metrics"][0]["value"])
        self.assertIn("entries", r["missing_target_fields"])

    def test_urls_and_credentials_are_not_retained(self):
        r = sources.normalize_capture(self.capture())
        self.assertEqual(r["source_url"], "https://example.douyin.com/review")
        self.assertNotIn("secret", json.dumps(r))
        self.assertNotIn("never-save", json.dumps(r))

    def test_metric_units_and_rounding(self):
        self.assertEqual(sources.metric_value("1.2万", "count"), (12000, True))
        self.assertEqual(sources.metric_value("30%", "percent"), (0.3, False))
        for raw, unit in [(True, "count"), (float("nan"), "count"),
                          (-1, "count"), (1.2, "count"), (2, "ratio"),
                          (101, "percent"), ("30%", "count")]:
            with self.assertRaises(ValueError):
                sources.metric_value(raw, unit)

    def test_union_backend_is_supported_without_private_queries(self):
        value = "https://union.bytedance.com/open/portal/anchor/list/anchorDetail?anchorID=private&tab=live_record"
        self.assertEqual(sources.clean_backend_url(value),
                         "https://union.bytedance.com/open/portal/anchor/list/anchorDetail")
        for value in ["https://union.bytedance.com.evil.example/review",
                      "https://unrelated.bytedance.com/review", "http://union.bytedance.com/review"]:
            with self.assertRaises(ValueError):
                sources.clean_backend_url(value)

    def test_unknown_kind_field_and_naive_time_fail(self):
        for mutate in [lambda x: x.update(captured_at="2026-10-03T12:00:00"),
                       lambda x: x["metrics"][0].update(key="cookie"),
                       lambda x: x["metrics"][0].update(kind="unknown")]:
            capture = self.capture()
            mutate(capture)
            with self.assertRaises(ValueError):
                sources.normalize_capture(capture)

    def test_synthetic_input_remains_flagged_without_invented_rates(self):
        capture = self.capture(10)
        capture["example_only"] = True
        r = sources.normalize_capture(capture)
        self.assertTrue(r["example_only"])
        self.assertEqual(r["derived_rates"], {})
        self.assertEqual(r["alignment_status"], "not_aligned")


if __name__ == "__main__":
    unittest.main()
