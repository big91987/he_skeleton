import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from full_harness import router, runner
from full_harness.common import controls

class RoutingTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name)
        self.work=self.root/'workspace';self.work.mkdir()
        (self.work/'prd.md').write_text('Existing requirements and acceptance criteria')
        (self.work/'code.py').write_text('print("real code")')
        self.state={'task':{'number':1,'body':'Implement the feature'},'instruction':'','stage':'entry','status':'running',
            'turn':0,'completed':{},'controls':controls(self.work),'config':{'max_attempts':2,'check_timeout':5,
            'checks':[{'name':'actual check','argv':[sys.executable,'-c','from pathlib import Path; assert Path("fixed").exists()']}]}}
    def decision(self,actions):
        return {'status':'ready','summary':'Assessed actual materials','question':'','decisions':[
            {'stage':stage,'action':action,'reason':'Based on current task and materials',
             'evidence':(['code.py'] if stage=='development' else ['prd.md']) if action=='reuse' else []}
            for stage,action in zip(runner.STAGES[:3],actions)]}
    def apply(self,result):
        router.validate(result,self.work,self.state)
        with patch.object(runner,'classify',return_value=result):runner.assess_entry(self.root,self.root,self.state)
    def test_idea_starts_requirements(self):
        self.apply(self.decision(['run']*3));self.assertEqual(self.state['stage'],'requirements')
    def test_existing_prd_starts_design(self):
        self.apply(self.decision(['reuse','run','run']));self.assertEqual(self.state['stage'],'requirements')
    def test_existing_code_enters_verification_not_delivery(self):
        self.apply(self.decision(['reuse','not_applicable','reuse']))
        self.assertEqual(self.state['stage'],'requirements')
        self.assertNotIn('review',self.state['completed'])
    def test_missing_evidence_cannot_skip_stage(self):
        result=self.decision(['reuse','run','run']);result['decisions'][0]['evidence']=['missing.md']
        with self.assertRaises(ValueError):router.validate(result,self.work,self.state)
    def test_current_issue_reference_is_canonical_through_approval(self):
        result=self.decision(['reuse','run','run'])
        result['decisions'][0]['evidence']=['issue #1','prd.md']
        self.apply(result)
        self.assertEqual(result['decisions'][0]['evidence'],['issue','prd.md'])
        self.assertIn('issue',result['decisions'][0]['evidence_hashes'])
        self.assertIn('issue',runner.material_hashes(self.root,self.state,'requirements'))
    def test_other_issue_reference_is_rejected(self):
        result=self.decision(['reuse','run','run'])
        result['decisions'][0]['evidence']=['issue #2']
        with self.assertRaises(ValueError):router.validate(result,self.work,self.state)
    def test_issue_alias_cannot_prove_existing_code(self):
        result=self.decision(['reuse','run','reuse'])
        result['decisions'][2]['evidence']=['Issue #1']
        with self.assertRaisesRegex(ValueError,'actual project files'):
            router.validate(result,self.work,self.state)
    def test_escape_and_illegal_stage_are_rejected(self):
        result=self.decision(['reuse','run','run']);result['decisions'][0]['evidence']=['../outside']
        with self.assertRaises(ValueError):router.validate(result,self.work,self.state)
        result=self.decision(['run']*3);result['decisions'][-1]['stage']='delivery'
        with self.assertRaises(ValueError):router.validate(result,self.work,self.state)
    def test_requirement_not_applicable_is_rejected(self):
        with self.assertRaises(ValueError):router.validate(self.decision(['not_applicable']*3),self.work,self.state)
    def test_clarification_pauses_entry(self):
        self.apply({'status':'needs_input','summary':'Need scope','question':'Which interface is in scope?','decisions':[]})
        self.assertEqual(self.state['stage'],'entry');self.assertEqual(self.state['status'],'needs_input')
    def test_existing_code_runs_real_check_without_builder(self):
        (self.work/'fixed').write_text('already correct')
        self.state['completed']={'development':{'mode':'reuse'}}
        with patch.object(runner,'run_agent',side_effect=AssertionError('must not code')):
            runner.verify_stage(self.root,self.root,self.state)
        self.assertEqual(self.state['stage'],'review')
        self.assertEqual(self.state['completed']['verification']['checks'][0]['code'],0)
    def test_failure_returns_to_builder_then_rechecks(self):
        self.state['completed']={'development':{'mode':'reuse'}}
        def repair(*args):(self.work/'fixed').write_text('repaired')
        with patch.object(runner,'run_agent',side_effect=repair) as builder:
            runner.verify_stage(self.root,self.root,self.state)
        self.assertEqual(builder.call_count,1);self.assertEqual(self.state['stage'],'review')
    def test_repeat_failures_stop_at_bound(self):
        with patch.object(runner,'run_agent') as builder:runner.verify_stage(self.root,self.root,self.state)
        self.assertEqual(builder.call_count,2);self.assertEqual(self.state['status'],'blocked')
    def test_routing_cannot_bypass_missing_owner_checks(self):
        self.state['config']['checks']=[]
        with self.assertRaises(ValueError):runner.verify_stage(self.root,self.root,self.state)

if __name__=='__main__':unittest.main()
