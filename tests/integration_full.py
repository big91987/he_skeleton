import json, os, sys, tempfile, shutil
from pathlib import Path
SOURCE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SOURCE))
from full_harness.codex import invoke
from full_harness.common import write_json
from full_harness.runner import new_state, run_agent, review_stage, begin, STAGES
source=SOURCE
if '--run-live' not in sys.argv:raise SystemExit('Opt-in required: python3 tests/integration_full.py --run-live; uses authenticated Codex and model quota')
root=Path(tempfile.mkdtemp(prefix='full-live-',dir=tempfile.gettempdir()));print('probe_root',root,flush=True)
work=root/'conversation';work.mkdir();session=root/'session';session.mkdir()
sid=None
for i,prompt in enumerate([
 '这是 Native Session 的受控验真。记住业务名 BlueShelf。现在向我澄清主色，用 needs_input 结果，不使用工具。',
 '主色蓝色。保持之前的业务名，再澄清布局密度，用 needs_input 结果，不使用工具。',
 '布局紧凑。用 ready 返回 summary，包含之前的业务名、主色和密度，不使用工具。']):
 result,current=invoke(source,work,session,prompt,root/('conversation-'+str(i)),session_id=sid)
 if sid:assert current==sid
 sid=current;print('conversation',i,current,result,flush=True)
assert all(x in result['summary'] for x in ['BlueShelf','蓝','紧凑'])
project=root/'project';shutil.copytree(source/'templates/full',project)
shutil.copytree(source/'full_harness',project/'full_harness',ignore=shutil.ignore_patterns('__pycache__'))
(project/'README.md').write_text('# CLI reading list\nA Python standard library command line program, no web UI.\n')
(project/'docs/00-global/project.md').write_text('# Project facts\nThis is a new CLI reading-list project. All product decisions below were supplied for this controlled integration test. Python 3 standard library, UTF-8 JSON file. Commands: add <title>, list, search <query>. --store <path> chooses data file. Search is case-insensitive substring matching. Empty search lists all. Each output is a JSON array of title strings. Duplicate titles are allowed. Adding persists and outputs the resulting array. Missing storage is empty. Invalid command and corrupt JSON must exit nonzero with useful stderr. No GUI, server, account, network, concurrent writers or delete feature.\n')
check='''import json, subprocess, sys, tempfile
from pathlib import Path
p=Path(tempfile.mkdtemp())/'books.json'
def call(*a):
 r=subprocess.run([sys.executable,'reading.py','--store',str(p),*a],capture_output=True,text=True);assert r.returncode==0,r.stderr;return json.loads(r.stdout)
assert call('list')==[]
assert call('add','Python Design')==['Python Design']
assert call('add','MaaS')==['Python Design','MaaS']
assert call('search','PYTHON')==['Python Design']
assert call('search','absent')==[]
assert call('search','')==['Python Design','MaaS']
p.write_text('broken')
r=subprocess.run([sys.executable,'reading.py','--store',str(p),'list'],capture_output=True,text=True)
assert r.returncode!=0 and r.stderr.strip()
print('Seven real CLI assertions passed')
'''
(project/'.harness/check_cli.py').write_text(check)
cfg=json.loads((project/'.harness/full.json').read_text());cfg['checks']=[{'name':'actual CLI round trip','argv':[sys.executable,'.harness/check_cli.py']}];cfg['agent_timeout']=900
write_json(project/'.harness/full.json',cfg)
session=root/'task';session.mkdir()
task={'number':7,'title':'Build CLI reading list','body':(project/'docs/00-global/project.md').read_text()+'\nImplement reading.py. Every decision in these facts is accepted by the test task Owner; do not invent further scope. Apply existing Skills only where applicable; use concise stage documents.'}
state=new_state(project,session,task,'owner/test','local-fixture','main','probe-runner')
state['instruction']='按已确认需求交付，每阶段阅读可复用 Skills。';state['run_id']='local-integration'
write_json(session/'state.json',state)
for stage in STAGES[:3]:
 print('starting',stage,flush=True)
 run_agent(project,session,state,stage);write_json(session/'state.json',state)
 print('stage',stage,state['status'],state.get('reason',''),flush=True)
 if state['status']=='awaiting_approval':
  begin(state,state['reply_token']+' approve','local-fixture','probe-runner','local-integration',session)
  print('synthetic Owner approved',stage,flush=True)
 if state['status']!='running':break
if state['status']=='running':
 print('starting independent review',flush=True);review_stage(project,session,state);write_json(session/'state.json',state)
print('FINAL',json.dumps({'root':str(root),'stage':state['stage'],'status':state['status'],'history':state['history'],'reason':state.get('reason','')},ensure_ascii=False),flush=True)
