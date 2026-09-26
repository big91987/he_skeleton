import contextlib
import io
import json
import os
import unittest
from unittest.mock import patch

from full_harness.console import Console


class ConsoleTests(unittest.TestCase):
    def output(self, events):
        output = io.StringIO()
        with (
            patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}),
            contextlib.redirect_stdout(output),
        ):
            console = Console()
            for event in events:
                console.feed(json.dumps(event) + "\n")
            console.finish()
        return output.getvalue()

    def test_readable_message_and_error(self):
        result = self.output(
            [
                {
                    "type": "item.completed",
                    "item": {
                        "type": "agent_message",
                        "text": json.dumps(
                            {
                                "summary": "PRD 已生成",
                                "status": "needs_input",
                                "question": "是否确认？",
                            }
                        ),
                    },
                },
                {"type": "turn.failed", "error": {"message": "timeout"}},
            ]
        )
        self.assertIn("Agent：\n[codex] PRD 已生成", result)
        self.assertIn("需要你回复", result)
        self.assertIn("执行失败", result)
        self.assertNotIn('"summary"', result)

    def test_group_escape_and_truncation(self):
        result = self.output(
            [
                {
                    "type": "item.completed",
                    "item": {
                        "type": "command_execution",
                        "command": "test\n::error::injected",
                        "exit_code": 1,
                        "aggregated_output": "::endgroup::\n::error::injected\n"
                        + "line\n" * 110,
                    },
                }
            ]
        )
        self.assertEqual(result.count("\n::endgroup::"), 1)
        self.assertNotIn("\n::error::", result)
        self.assertIn("命令失败", result)
        self.assertIn("页面省略", result)

    def test_partial_json_is_not_lost(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            console = Console()
            console.feed('{"type":"turn.')
            self.assertEqual(output.getvalue(), "")
            console.feed('started"}\nplain text')
            console.finish()
        self.assertIn("开始本轮执行", output.getvalue())
        self.assertIn("plain text", output.getvalue())
