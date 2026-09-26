import unittest

from full_harness.progress import progress_rows


class ProgressTests(unittest.TestCase):
    def test_confirmed_requirements_remain_complete_during_design(self):
        state = {
            "repo": "o/r",
            "task": {"number": 18},
            "stage": "design",
            "status": "running",
            "completed": {"requirements": {"artifact": "prd.md", "run_id": "11"}},
            "approvals": {"requirements": {"run_id": "12", "comment_id": 99}},
            "stage_runs": {"design": "12"},
        }
        text = "\n".join(progress_rows(state))
        self.assertIn("需求 ✅ 已确认 → 设计 ⏳ 进行中 → 研发 ○ 未开始", text)
        self.assertIn("issues/18#issuecomment-99", text)
        self.assertNotIn("[确认记录]", text)
        self.assertIn("runs/11", text)
        self.assertIn("runs/12", text)
        state.update(status="blocked", reason="Document approval mismatch")
        text = "\n".join(progress_rows(state))
        self.assertIn("需求 ✅ 已确认 → 设计 ⛔ 受阻", text)
        self.assertIn("Document approval mismatch", text)

    def test_confirmation_names_current_stage(self):
        state = {
            "repo": "o/r",
            "task": {"number": 18},
            "stage": "design",
            "status": "awaiting_approval",
        }
        self.assertIn("这版设计确认通过", "\n".join(progress_rows(state)))
