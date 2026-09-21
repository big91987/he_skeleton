import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from full_harness import runner, stop_hook
from full_harness.common import controls, digest, write_json
from scripts.install_full import plan


class FullWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.work=self.root/'workspace';self.work.mkdir()
        self.evidence=self.root/'evidence';self.evidence.mkdir()
        (self.work/'AGENTS.md').write_text('Immutable Owner rules')
        (self.work/'validation.md').write_text('Actual validation scope and evidence. '*10)
        self.cfg={'max_attempts':2,'agent_timeout':60,'check_timeout':5,'review_timeout':10,
                  'entries':['AGENTS.md'],'stages':{s:{'skills':[],'artifact':'validation.md'} for s in runner.STAGES[:4]},
                  'checks':[{'name':'real assertion','argv':[sys.executable,'-c','from pathlib import Path; assert Path("fixed").exists()']}]}
        self.context={'workspace':str(self.work),'evidence':str(self.evidence),'source':str(self.root),'session':str(self.root),
                      'controls':controls(self.work),'stage':'implementation','config':self.cfg,
                      'task':{'number':1},'deadline_monotonic':time.monotonic()+60}
        self.cp=self.root/'context.json';write_json(self.cp,self.context)
        self.ready={'last_assistant_message':json.dumps({'status':'ready','summary':'done','question':'','artifacts':['validation.md']})}

    def test_failing_real_check_then_same_gate_pass(self):
        failure=stop_hook.evaluate(self.cp,self.ready)
        self.assertEqual(failure['decision'],'block')
        (self.work/'fixed').write_text('now actually fixed')
        self.assertEqual(stop_hook.evaluate(self.cp,self.ready),{})
        gate=json.loads((self.evidence/'gate.json').read_text())
        self.assertEqual(gate['status'],'passed');self.assertEqual(gate['snapshot'],digest(self.work))
        self.assertEqual(gate['attempts'],2)

    def test_checks_cannot_be_bypassed_by_mutating_controls(self):
        (self.work/'AGENTS.md').write_text('Weakened acceptance')
        stop_hook.evaluate(self.cp,self.ready)
        self.assertEqual(json.loads((self.evidence/'gate.json').read_text())['status'],'blocked')

    def test_no_applicable_implementation_check_blocks(self):
        self.context['config']['checks'][0]['stages']=['design'];write_json(self.cp,self.context)
        stop_hook.evaluate(self.cp,self.ready)
        self.assertEqual(json.loads((self.evidence/'gate.json').read_text())['status'],'blocked')

    def test_clarification_does_not_run_checks(self):
        with patch.object(stop_hook,'run_process',side_effect=AssertionError('must not run')):
            stop_hook.evaluate(self.cp,{'last_assistant_message':json.dumps({'status':'needs_input','question':'Which user role?'})})
        self.assertEqual(json.loads((self.evidence/'gate.json').read_text())['status'],'needs_input')

    def test_review_failure_requests_repair_not_success(self):
        self.context['stage']='requirements';write_json(self.cp,self.context)
        with patch.object(stop_hook,'review_prompt',return_value='review'),patch.object(stop_hook,'invoke',return_value=({'status':'changes','findings':['Missing creation path'],'summary':'gap'},'review-session')):
            result=stop_hook.evaluate(self.cp,self.ready)
        self.assertIn('Missing creation path',result['reason'])

    def test_wall_clock_jump_does_not_expire_active_gate(self):
        (self.work/'fixed').write_text('fixed')
        with patch.object(stop_hook.time,'time',return_value=10**12):
            stop_hook.evaluate(self.cp,self.ready)
        self.assertEqual(json.loads((self.evidence/'gate.json').read_text())['status'],'passed')

    def test_attempt_limit_stops_loop(self):
        for _ in range(3):stop_hook.evaluate(self.cp,self.ready)
        self.assertEqual(json.loads((self.evidence/'gate.json').read_text())['status'],'blocked')

    def test_owner_and_exact_command(self):
        event={'action':'created','issue':{'number':3},'comment':{'body':'/develop token answer'}}
        with patch.dict(os.environ,{'GITHUB_TRIGGERING_ACTOR':'owner'}):
            self.assertEqual(runner.event_input(event,'owner/repo','owner','issue_comment'),(3,'token answer'))
            with self.assertRaises(ValueError):runner.event_input(event,'owner/repo','stranger','issue_comment')
            event['comment']['body']='/developer'
            with self.assertRaises(ValueError):runner.event_input(event,'owner/repo','owner','issue_comment')

    def test_stale_reply_and_base_drift_rejected(self):
        state={'runner':'machine','baseline':'sha','status':'needs_input','reply_token':'new'}
        with self.assertRaises(ValueError):runner.begin(state,'old yes','sha','machine','1')
        with self.assertRaises(ValueError):runner.begin(state,'new yes','changed','machine','1')
        runner.begin(state,'new yes','sha','machine','1')
        self.assertEqual(state['instruction'],'yes');self.assertEqual(state['status'],'running')

    def test_missing_hook_gate_never_passes(self):
        state={'config':self.cfg,'task':{'number':1},'turn':0,'controls':controls(self.work),'baseline':'sha','history':[],
               'completed':{},'status':'running','stage':'implementation'}
        with patch.object(runner,'prompt_for',return_value='task'),patch.object(runner,'invoke',return_value=({'status':'ready','summary':'claimed','question':'','artifacts':[]},'builder')):
            runner.work_stage(self.root,self.root,state,'implementation')
        self.assertEqual(state['status'],'blocked');self.assertEqual(state['completed'],{})

    def test_independent_review_returns_to_affected_stage(self):
        state={'config':self.cfg,'task':{'number':1},'turn':0,'baseline':'sha','history':[],'completed':{'implementation':{}},'status':'running','stage':'review'}
        calls=[]
        def repair(source,session,s,stage):
            calls.append(stage);s['completed'][stage]={'checks':[]};s['stage']=runner.STAGES[runner.STAGES.index(stage)+1]
        outcomes=[({'status':'changes','summary':'fix interface','question':'','return_stage':'design','findings':['contract missing']},'review1'),
                  ({'status':'passed','summary':'verified','question':'','return_stage':'implementation','findings':[]},'review2')]
        with patch.object(runner,'review_prompt',return_value='review'),patch.object(runner,'invoke',side_effect=outcomes),patch.object(runner,'work_stage',side_effect=repair),patch.object(runner,'verify_stage'):
            runner.review_stage(self.root,self.root,state)
        self.assertEqual(calls,['design','plan','implementation']);self.assertEqual(state['stage'],'delivery')

    def test_install_and_upgrade_preserve_owner_files(self):
        (self.work/'.git').mkdir()
        templates={'AGENTS.md':b'template','.github/workflows/harness-full.yml':b'original'}
        changes=plan(self.work,{'full_harness/a.py':b'v1'},templates,'revision1')
        for n,b in changes.items():
            p=self.work/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
        (self.work/'.github/workflows/harness-full.yml').write_text('owner changed')
        result=plan(self.work,{'full_harness/a.py':b'v2'},templates,'revision2')
        self.assertNotIn('AGENTS.md',result);self.assertNotIn('.github/workflows/harness-full.yml',result)
        (self.work/'full_harness/a.py').write_text('local change')
        with self.assertRaises(ValueError):plan(self.work,{'full_harness/a.py':b'v3'},templates,'revision3')

    def test_installer_rejects_symlink_escape(self):
        outside=self.root/'outside';outside.mkdir()
        (self.work/'full_harness').symlink_to(outside,target_is_directory=True)
        with self.assertRaises(ValueError):plan(self.work,{'full_harness/a.py':b'bad'}, {},'revision')

    def test_delivery_retry_reuses_commit_after_pr_permission_failure(self):
        state={'repo':'owner/repo','branch':'main','baseline':'base','task':{'number':1,'title':'change'},
               'controls':controls(self.work),'baseline_files':{},'baseline_modes':{},
               'completed':{'review':{'snapshot':digest(self.work)}}}
        remote={'ref':None,'commits':0,'allow_pr':False}
        def api(repo,path,method='GET',data=None):
            if path=='commits/main':return {'sha':'base','commit':{'tree':{'sha':'oldtree'}}}
            if path=='git/blobs':return {'sha':'blob'}
            if path.startswith('git/matching-refs'):
                return [] if not remote['ref'] else [{'ref':'refs/heads/codex/full-task-1','object':{'sha':remote['ref']}}]
            if path=='git/trees':return {'sha':'tree'}
            if path=='git/commits':remote['commits']+=1;return {'sha':'newcommit'}
            if path=='git/refs':remote['ref']=data['sha'];return {}
            if path.startswith('pulls?'):return []
            if path=='pulls':
                if not remote['allow_pr']:raise RuntimeError('PR permission denied')
                return {'html_url':'https://github.com/owner/repo/pull/2'}
            raise AssertionError(path)
        with patch.object(runner,'api',side_effect=api):
            with self.assertRaises(RuntimeError):runner.deliver(self.root,state)
            self.assertEqual(state['delivery_commit'],'newcommit')
            remote['allow_pr']=True;runner.deliver(self.root,state)
        self.assertEqual(remote['commits'],1);self.assertEqual(state['status'],'waiting_review')

    def test_human_pr_feedback_invalidates_acceptance_and_resumes_implementation(self):
        state={'runner':'machine','baseline':'sha','status':'waiting_review','reply_token':'reply',
               'stage':'delivery','completed':{'requirements':{},'design':{},'plan':{},'implementation':{},'review':{},'delivery':{}}}
        runner.begin(state,'reply fix empty results','sha','machine','next-run')
        self.assertEqual(state['stage'],'entry')
        self.assertEqual(set(state['completed']),{'requirements','design','plan'})
        self.assertEqual(state['instruction'],'fix empty results')

    def test_cancelled_call_recovers_native_session_mapping(self):
        sid='11111111-2222-4333-8444-555555555555'
        log=self.root/'turns/1/agent/agent.jsonl';log.parent.mkdir(parents=True)
        log.write_text(json.dumps({'type':'thread.started','thread_id':sid})+'\n')
        self.assertEqual(runner.recover_session(self.root),sid)
        write_json(self.root/'codex-session.json',{'session_id':'99999999-2222-4333-8444-555555555555'})
        with self.assertRaises(ValueError):runner.recover_session(self.root)

    def test_mode_change_invalidates_snapshot(self):
        before=digest(self.work);(self.work/'validation.md').chmod(0o755)
        self.assertNotEqual(before,digest(self.work))


if __name__=='__main__':unittest.main()
