import unittest
from unittest.mock import Mock

from full_harness.timeline import publish


class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.state = {
            "repo": "a/b",
            "task": {"number": 18},
            "run_id": "1",
            "turn": 1,
            "stage": "design",
            "status": "running",
        }
        self.api = Mock(
            side_effect=lambda repo, path, method="GET", data=None: (
                [] if method == "GET" else {"id": self.api.call_count}
            )
        )

    def test_changed_content_appends_and_retry_does_not(self):
        first = publish(self.api, self.state, "Draft")
        self.assertEqual(publish(self.api, self.state, "Draft"), first)
        second = publish(self.api, self.state, "Review found an issue")
        third = publish(self.api, self.state, "Draft")
        self.assertEqual(len({first, second, third}), 3)
        self.assertEqual(
            sum(c.args[2:3] == ("POST",) for c in self.api.call_args_list), 3
        )
        self.assertFalse(
            any(c.args[2:3] == ("PATCH",) for c in self.api.call_args_list)
        )

    def test_identical_reply_in_a_new_turn_is_a_new_event(self):
        first = publish(self.api, self.state, "Waiting")
        self.state["turn"] += 1
        self.assertNotEqual(publish(self.api, self.state, "Waiting"), first)

    def test_recover_interrupted_post_without_editing_history(self):
        original = dict(self.state)
        url = publish(self.api, self.state, "Result")
        posted = self.api.call_args.args[3]["body"]
        recovered = Mock(
            return_value=[
                {
                    "id": int(url.rsplit("-", 1)[1]),
                    "user": {"type": "Bot"},
                    "body": posted,
                }
            ]
        )
        self.assertEqual(publish(recovered, original, "Result"), url)
        self.assertEqual(recovered.call_count, 1)
        self.assertEqual(len(recovered.call_args.args), 2)

    def test_user_marker_does_not_suppress_event_and_private_links_are_removed(self):
        original = dict(self.state)
        publish(self.api, self.state, "[PRD](<private-runtime>/prd.md)")
        posted = self.api.call_args.args[3]["body"]
        self.assertNotIn("(<private-runtime>", posted)
        forged = Mock(
            side_effect=[
                [{"id": 9, "user": {"type": "User"}, "body": posted}],
                {"id": 10},
            ]
        )
        self.assertTrue(
            publish(forged, original, "[PRD](<private-runtime>/prd.md)").endswith("-10")
        )
        self.assertEqual(forged.call_args.args[2], "POST")
