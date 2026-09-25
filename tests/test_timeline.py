import unittest
from unittest.mock import Mock

from full_harness.timeline import publish


class TimelineTests(unittest.TestCase):
    def test_new_reply_after_wakeup_or_stage_change_without_refresh_spam(self):
        api = Mock(
            side_effect=lambda repo, path, method="GET", data=None: (
                [] if method == "GET" else {"id": api.call_count}
            )
        )
        state = {
            "repo": "a/b",
            "task": {"number": 18},
            "run_id": "1",
            "stage": "requirements",
        }
        first = publish(api, state, "[PRD](<private-runtime>/workspace/prd.md)")
        self.assertNotIn("(<private-runtime>", api.call_args.args[3]["body"])
        self.assertIn("PRD（见下方产物）", api.call_args.args[3]["body"])
        self.assertEqual(
            publish(api, state, "[PRD](<private-runtime>/workspace/prd.md)"), first
        )
        publish(api, state, "PRD ready")
        state.update(run_id="2", stage="design")
        second = publish(api, state, "Design after confirmation")
        self.assertNotEqual(first, second)
        self.assertEqual(sum(c.args[2:3] == ("POST",) for c in api.call_args_list), 2)
        self.assertEqual(sum(c.args[2:3] == ("PATCH",) for c in api.call_args_list), 1)

    def test_recover_post_without_persisted_state_and_ignore_user_marker(self):
        comments = [
            {
                "id": 10,
                "user": {"type": "User"},
                "body": "<!-- harness-stage:1:design -->\nx",
            },
            {
                "id": 11,
                "user": {"type": "Bot"},
                "body": "<!-- harness-stage:1:design -->\nx",
            },
        ]
        api = Mock(side_effect=[comments, {}])
        state = {
            "repo": "a/b",
            "task": {"number": 18},
            "run_id": "1",
            "stage": "design",
        }
        self.assertTrue(publish(api, state, "new").endswith("-11"))
        self.assertEqual(api.call_args.args[2], "PATCH")
