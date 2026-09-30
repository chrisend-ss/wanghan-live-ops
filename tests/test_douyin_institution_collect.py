import unittest

from tools.douyin_institution_collect import (
    discover_metrics,
    parse_page_identity,
    redact_url,
)


class DouyinInstitutionCollectorTest(unittest.TestCase):
    def test_parse_page_identity(self):
        url = (
            "https://union.bytedance.com/open/portal/anchor/list/liveRecordDetail"
            "?anchorID=7465741188222436411&appId=3000&roomID=7690925801470053129"
        )
        identity = parse_page_identity(url)
        self.assertEqual(identity.anchor_id, "7465741188222436411")
        self.assertEqual(identity.room_id, "7690925801470053129")
        self.assertEqual(identity.app_id, "3000")

    def test_redact_url_removes_query(self):
        self.assertEqual(
            redact_url("https://union.bytedance.com/api/x?a=1&token=secret"),
            "https://union.bytedance.com/api/x",
        )

    def test_discover_metrics_keeps_source_path(self):
        payloads = [
            {
                "url": "https://union.bytedance.com/api/detail",
                "body": {
                    "data": {
                        "show_uv": 1000,
                        "watch_uv": 220,
                        "max_online": 88,
                    }
                },
            }
        ]
        metrics = discover_metrics(payloads)
        self.assertEqual(metrics["exposure_uv"]["value"], 1000)
        self.assertEqual(metrics["viewer_uv"]["value"], 220)
        self.assertEqual(metrics["max_online"]["value"], 88)
        self.assertEqual(metrics["exposure_uv"]["confidence"], "provisional")


if __name__ == "__main__":
    unittest.main()
