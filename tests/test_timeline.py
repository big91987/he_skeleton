import html
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from full_harness.timeline import AgentReplies, publish


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

    def test_progress_recovers_lost_post_and_updates_one_fold_without_losing_history(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "progress.json"
            comments = []
            posts = []
            patches = []

            def api(repo, target, method="GET", data=None):
                if method == "GET":
                    return comments
                if method == "POST":
                    posts.append(data["body"])
                    comments.append(
                        {"id": 77, "user": {"type": "Bot"}, "body": data["body"]}
                    )
                    raise RuntimeError("Response lost after GitHub accepted POST")
                patches.append(data["body"])
                comments[0]["body"] = data["body"]
                return {"id": 77}

            first = AgentReplies(api, self.state, path, ("/private/task",))
            first(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "one",
                        "type": "agent_message",
                        "phase": "commentary",
                        "text": "先检查 /private/task/workspace",
                    },
                }
            )
            resumed = AgentReplies(api, self.state, path, ("/private/task",))
            resumed(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "two",
                        "type": "agent_message",
                        "phase": "commentary",
                        "text": "找到接口差异",
                    },
                }
            )
            self.assertEqual(len(posts), 1)
            self.assertEqual(len(patches), 1)
            self.assertIn("先检查", patches[0])
            self.assertIn("找到接口差异", patches[0])
            self.assertIn("[codex] 先检查", patches[0])
            self.assertIn("[codex] 找到接口差异", patches[0])
            self.assertIn("[harness] **执行中**", patches[0])
            self.assertIn("[harness] [运行日志]", patches[0])
            self.assertIn("<details>", patches[0])
            self.assertNotIn("/private/task", patches[0])
            self.assertEqual(resumed.record["comment_id"], 77)

            self.assertIn('"type": "item.completed"', html.unescape(patches[-1]))
            self.assertIn("执行中", patches[-1])
            raw = json.loads(
                html.unescape(re.search(r"<pre>(.*?)</pre>", patches[-1], re.S)[1])
            )
            self.assertEqual([e["item"]["id"] for e in raw], ["one", "two"])
            complete = {"type": "turn.completed", "usage": {"output_tokens": 3}}
            resumed(complete)
            self.assertEqual(resumed.record["execution_event"], complete)
            self.assertIn("本轮输出已结束", patches[-1])
            resumed.finish(True)
            self.assertIn("本轮已结束", patches[-1])
            resumed.finish(False)
            self.assertIn("执行失败", patches[-1])
            self.assertEqual(resumed.record["execution_event"], complete)
            self.assertEqual(len(posts), 1)

    def test_large_progress_keeps_all_events_across_bounded_comments(self):
        with tempfile.TemporaryDirectory() as directory:
            comments = {}

            def api(repo, target, method="GET", data=None):
                if method == "GET":
                    return [
                        {"id": i, "user": {"type": "Bot"}, "body": b}
                        for i, b in comments.items()
                    ]
                number = (
                    len(comments) + 1
                    if method == "POST"
                    else int(target.rsplit("/", 1)[1])
                )
                comments[number] = data["body"]
                return {"id": number}

            path = Path(directory) / "progress.json"
            replies = AgentReplies(api, self.state, path)
            events = []
            for text in ("第一条<&>" * 3000, "第二条甲乙丙" * 3000):
                event = {
                    "type": "item.completed",
                    "item": {
                        "id": "same-id",
                        "type": "agent_message",
                        "phase": "commentary",
                        "text": text,
                    },
                }
                events.append(event)
                replies(event)
            self.assertGreater(len(comments), 1)
            self.assertTrue(
                all(len(b.encode("utf-8")) < 60000 for b in comments.values())
            )
            raw = "".join(
                html.unescape(m[1])
                for b in comments.values()
                if (m := re.search(r"<pre>(.*?)</pre>", b, re.S))
            )
            self.assertEqual(json.loads(raw), events)
            self.assertEqual(
                list(replies.record["messages"].values()),
                [e["item"]["text"] for e in events],
            )
            count = len(comments)
            AgentReplies(api, self.state, path).finish(True)
            self.assertEqual(len(comments), count)
            self.assertTrue(all("本轮已结束" in b for b in comments.values()))
