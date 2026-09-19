import json, os, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'harness'))
import project, loop

class ProjectPolicy(unittest.TestCase):
 def test_empty_and_python_project_need_no_html(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);self.assertEqual(project.files(root),{})
   (root/'main.py').write_text('print(1)');(root/'README.md').write_text('CLI')
   self.assertEqual(set(project.files(root)),{'main.py','README.md'})
 def test_browser_is_opt_in_and_invalid_verifier_is_not_substituted(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);self.assertEqual(project.settings(root),{})
   (root/'harness-project.json').write_text(json.dumps({'verification':{'kind':'static-browser','root':'ui'}}))
   self.assertEqual(project.settings(root)['verification']['root'],'ui')
   (root/'harness-project.json').write_text(json.dumps({'verification':{'kind':'unknown'}}))
   with self.assertRaises(ValueError):project.settings(root)
 def test_control_files_cannot_be_modified(self):
  with self.assertRaises(ValueError):project.check_control_changes({'harness-project.json':b'old'},{'harness-project.json':b'new'})
 def test_generic_prompt_does_not_require_browser_plan(self):
  p=project.prompt({'title':'Python CLI','body':'No website'},[],{})
  self.assertNotIn('Create app/acceptance.json',p)
  self.assertIn('No automatic verifier',p)

class NonWebExecution(unittest.TestCase):
 def exercise(self,clarify):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);source=root/'source';source.mkdir()
   event={'repository':{'owner':{'login':'owner'},'full_name':'owner/repo'},'sender':{'login':'owner'},'action':'opened','issue':{'id':77,'number':7,'labels':[{'name':'harness'}]},'inputs':{'task':'7','instruction':'Implement CLI'}}
   ep=root/'event.json';ep.write_text(json.dumps(event))
   env={'GITHUB_EVENT_PATH':str(ep),'GITHUB_EVENT_NAME':'issues' if clarify else 'workflow_dispatch','GITHUB_REPOSITORY':'owner/repo','GITHUB_RUN_ID':'500','HARNESS_ROOT':str(root),'RUNNER_TEMP':str(root/'tmp'),'GITHUB_OUTPUT':str(root/'out'),'HARNESS_EXPERIMENT':''}
   def api(method,path,body=None):
    if method=='POST':return {}
    if '/issues/' in path:return {'title':'CLI','body':'Python command-line tool','state':'open'}
    if '/git/ref/' in path:return {'object':{'sha':'old'}}
    if '/pulls?' in path:return []
    return {'default_branch':'main'}
   def agent(workspace,prompt,evidence,**kw):
    if clarify:return {'status':'needs_input','summary':'scope','question':'Which input format?'}
    self.assertTrue((workspace/'docs/PRD.md').exists())
    (workspace/'main.py').write_text('print("CLI")')
    return {'status':'ready','summary':'CLI implemented; verification pending','question':''}
   def restore(repo,sha,target,**kw):
    self.assertEqual(kw['prefix_path'],'')
    if not clarify:
     (target/'docs').mkdir();(target/'docs/PRD.md').write_text('CLI product requirements')
   with patch.dict(os.environ,env),patch.object(loop,'SOURCE',source),patch.object(loop,'gh',side_effect=api),patch.object(loop,'restore_app',side_effect=restore),patch.object(loop,'run_agent',side_effect=agent),patch.object(loop,'publish_code',return_value='new') as publish,patch.object(loop.subprocess,'run') as browser:
    loop.main();browser.assert_not_called()
    state=json.loads((root/'sessions/7/state.json').read_text())
    if clarify:
     self.assertEqual(state['status'],'waiting_input');publish.assert_not_called()
    else:
     self.assertEqual(state['status'],'needs_verification')
     self.assertIn('main.py',publish.call_args.args[3])
     self.assertIn('docs/PRD.md',publish.call_args.args[3])
     self.assertEqual(publish.call_args.kwargs['prefix_path'],'')
     self.assertFalse((root/'sessions/7/workspace/index.html').exists())
 def test_empty_project_clarification(self):self.exercise(True)
 def test_cli_code_and_docs_saved_without_fake_browser_pass(self):self.exercise(False)
