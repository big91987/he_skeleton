import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "harness"))
from delivery import card


class DeliveryCard(unittest.TestCase):
    def test_non_web_evidence_does_not_advertise_web_application(self):
        result = {
            "task": 1,
            "sha": "a" * 40,
            "summary": "CLI execution result",
            "screenshots": [["运行截图", "screenshot.png"]],
        }
        text = card(
            result,
            "https://example.test/evidence/",
            {"passed": False, "performed": []},
            "owner/repo",
            "https://example.test/run",
        )
        self.assertIn("![运行截图]", text)
        self.assertIn("失败", text)
        self.assertNotIn("打开本轮应用", text)
        self.assertIn("人工验收：待确认", text)

    def test_web_card_links_version_and_actual_preview(self):
        result = {
            "task": 1,
            "scope": "isolated",
            "sha": "b" * 40,
            "summary": "ready",
            "preview_kind": "static-web",
            "experiment": "codex/harness-test-a",
        }
        text = card(
            result,
            "https://example.test/round2/",
            {"passed": True, "performed": [{}] * 16},
            "owner/repo",
            "https://example.test/run",
        )
        self.assertIn("16 个", text)
        self.assertIn("打开本轮应用", text)
        self.assertIn("/commit/" + "b" * 40, text)
        self.assertIn("Issue 评论路由尚未接通", text)
