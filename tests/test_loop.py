import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'harness'))
import loop


class TrustAndRecovery(unittest.TestCase):
    def event(self, user='owner', body='/harness 请加筛选'):
        return {'repository':{'owner':{'login':'owner'}},'sender':{'login':user},
                'comment':{'body':body,'id':42},'issue':{'number':7}}

    def test_nonowner_cannot_trigger(self):
        with self.assertRaises(PermissionError):
            loop.command(self.event('stranger'),'issue_comment')

    def test_plain_conversation_does_not_trigger(self):
        with self.assertRaises(ValueError):
            loop.command(self.event(body='please execute this'),'issue_comment')

    def test_prefix_collision_rejected(self):
        with self.assertRaises(ValueError):
            loop.command(self.event(body='/harness-bypass'),'issue_comment')

    def test_multiline_feedback_and_stable_event_id(self):
        self.assertEqual(loop.command(self.event(body='/harness 修改\n继续'),'issue_comment'),(7,'修改\n继续','comment-42'))

    def test_checkpoint_survives_new_reader(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'state.json'
            loop.atomic(p,{'status':'waiting_input','history':[{'user':'先问我'}]})
            self.assertEqual(json.loads(p.read_text())['history'][0]['user'],'先问我')
            self.assertFalse(p.with_suffix('.tmp').exists())

    def test_preview_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'index.html').write_text('ok');(root/'leak.txt').symlink_to('/etc/hosts')
            with self.assertRaises(ValueError):loop.app_files(root)

    def test_preview_rejects_secret_files(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'index.html').write_text('ok');(root/'.env').write_text('secret')
            with self.assertRaises(ValueError):loop.app_files(root)

    def test_code_publisher_does_not_overwrite_new_remote_head(self):
        calls=[]
        def fake(method,path,body=None):
            calls.append((method,path,body))
            if '/git/ref/heads/' in path:return {'object':{'sha':'latest-head'}}
            if '/git/commits/latest-head' in path:return {'tree':{'sha':'tree'}}
            if '?recursive=1' in path:return {'tree':[]}
            if path.endswith('/git/blobs'):return {'sha':'blob'}
            if path.endswith('/git/trees'):return {'sha':'new-tree'}
            if path.endswith('/git/commits'):return {'sha':'new-commit'}
            return {}
        with patch.object(loop,'gh',side_effect=fake):
            with self.assertRaisesRegex(RuntimeError,'Branch changed'):
                loop.publish_code('o/r','codex/task-7','old-base',{'index.html':b'ok'},'update')
            loop.publish_code('o/r','codex/task-7','latest-head',{'index.html':b'ok'},'update')
        commit=next(c[2] for c in calls if c[1].endswith('/git/commits'))
        self.assertEqual(commit['parents'],['latest-head'])
        self.assertFalse(calls[-1][2]['force'])


if __name__=='__main__':unittest.main()
