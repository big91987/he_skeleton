import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from full_harness import runner, stop_hook, router
from full_harness.skills import configure
from full_harness.common import write_json


class AgentInputTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.state={'task':{'number':8,'body':'ORIGINAL_TASK_MARKER'},'instruction':'initial',
                    'completed':{},'config':{'entries':['AGENTS.md'],'checks':[],'review_timeout':10,
                    'stages':{'requirements':{'instruction':'define AC','skills':['a'],'artifact':'prd.md'},
                              'design':{'instruction':'design interfaces','skills':['b'],'artifact':'design.md'}}}}

    def previous(self,packet,started=True):
        p=self.root/'turns/1/agent';p.mkdir(parents=True)
        write_json(p/'input.json',packet)
        if started:(p/'agent.jsonl').write_text(json.dumps({'type':'thread.started','thread_id':'id'})+'\n'+json.dumps({'type':'turn.completed'})+'\n')

    def test_resume_only_sends_new_answer(self):
        first,packet=runner.agent_input(self.state,'requirements',self.root)
        self.previous(packet);self.state['instruction']='search titles and body'
        prompt,_=runner.agent_input(self.state,'requirements',self.root)
        self.assertIn('search titles and body',prompt)
        self.assertNotIn('ORIGINAL_TASK_MARKER',prompt)
        self.assertNotIn('define AC',prompt)
        self.assertNotIn('handoff_artifact',prompt)

    def test_stage_change_updates_policy_without_replaying_task(self):
        _,packet=runner.agent_input(self.state,'requirements',self.root);self.previous(packet)
        prompt,_=runner.agent_input(self.state,'design',self.root)
        self.assertIn('design interfaces',prompt);self.assertIn('design.md',prompt)
        self.assertIn('"b"',prompt);self.assertNotIn('ORIGINAL_TASK_MARKER',prompt)

    def test_unstarted_call_does_not_suppress_initial_context(self):
        _,packet=runner.agent_input(self.state,'requirements',self.root);self.previous(packet,False)
        prompt,_=runner.agent_input(self.state,'requirements',self.root)
        self.assertIn('ORIGINAL_TASK_MARKER',prompt)

    def test_skill_body_is_never_read_by_prompt_builder(self):
        with patch.object(Path,'read_text',side_effect=AssertionError('No Skill body reads')):
            prompt,_=runner.agent_input(self.state,'requirements',self.root)
        self.assertIn('allowed_skills',prompt)

    def test_document_reviewer_does_not_invoke_author_skills(self):
        self.state['config']['stages']['design']['instruction']='CREATE DESIGN using $author-skill'
        prompt=stop_hook.review_prompt(self.root,self.root,self.state,'design')
        self.assertNotIn('$author-skill',prompt)
        self.assertIn('仅评审当前阶段',prompt)

    def test_router_does_not_invoke_stage_skills(self):
        self.state['config']['stages']['design']['instruction']='CREATE DESIGN using $author-skill'
        response={'status':'needs_input','summary':'unclear','question':'Which goal?','decisions':[]}
        with patch.object(router,'invoke',return_value=(response,'id')) as call:
            router.classify(self.root,self.root,self.root,self.state,self.root/'evidence')
        self.assertNotIn('$author-skill',call.call_args.args[3])
        self.assertEqual(call.call_args.kwargs['skills'],[])


@unittest.skipUnless(shutil.which('codex'),'Native Codex CLI not installed')
class NativeCatalogTests(unittest.TestCase):
    def test_native_stage_allowlist_and_scope_switch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';work=root/'work';home=root/'home'
            work.mkdir();home.mkdir();(work/'.git').mkdir()
            body='BODY_MUST_NOT_BE_INJECTED_7b019'
            for name,base in [('stage-a',source/'full_harness/skills'),('stage-b',source/'full_harness/skills'),
                              ('stage-a',work/'.agents/skills'),('unrelated',work/'.agents/skills')]:
                p=base/name;p.mkdir(parents=True);(p/'SKILL.md').write_text('---\nname: '+name+'\ndescription: Synthetic catalog fixture.\n---\n'+body)
            config='approval_policy="never"\nsandbox_mode="read-only"\n'
            for name in ['stage-a','stage-b']:
                evidence=root/name;evidence.mkdir()
                items=configure(home,work,source,[name],config,evidence)
                self.assertEqual([x['name'] for x in items],[name])
                self.assertEqual(Path(items[0]['path']).resolve(),(source/'full_harness/skills'/name/'SKILL.md').resolve())
                self.assertNotIn(body,(evidence/'skills.json').read_text())
            evidence=root/'no-skills';evidence.mkdir()
            self.assertEqual(configure(home,work,source,[],config,evidence),[])
            with self.assertRaises(ValueError):configure(home,work,source,['../escape'],config,evidence)


if __name__=='__main__':unittest.main()
