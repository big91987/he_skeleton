import json, sys, tempfile, time
from pathlib import Path
SOURCE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SOURCE))
from full_harness.codex import invoke
from full_harness.common import controls, write_json, read_json, digest
if '--run-live' not in sys.argv:raise SystemExit('Opt-in required: python3 tests/integration_stop.py --run-live; uses authenticated Codex and model quota')
source=SOURCE;root=Path(tempfile.mkdtemp(prefix='full-hook-live-',dir=tempfile.gettempdir()));work=root/'workspace';work.mkdir();evidence=root/'evidence';evidence.mkdir()
(work/'validation.md').write_text('Fault injection test: the first ready is deliberately premature. Acceptance requires fixed.txt containing verified. The native hook must reject the first attempt, then allow a real repair.\n')
(work/'.harness').mkdir();(work/'.harness/check.py').write_text('from pathlib import Path\nassert Path("fixed.txt").read_text().strip()=="verified"\n')
cfg={'max_attempts':3,'agent_timeout':360,'check_timeout':20,'stages':{'implementation':{'artifact':'validation.md'}},'checks':[{'name':'required file contents','argv':[sys.executable,'.harness/check.py']}]}
context={'source':str(source),'workspace':str(work),'session':str(root),'evidence':str(evidence),'stage':'implementation','task':{'number':1},'config':cfg,'controls':controls(work),'deadline':time.time()+360}
write_json(root/'context.json',context)
result,sid=invoke(source,work,root,'This is an explicit fault-injection test of the native Stop Hook. First return ready immediately, with artifacts ["validation.md"], without using tools or creating fixed.txt. When the hook rejects this premature ready, comply with its repair instruction by creating fixed.txt containing exactly verified, then return ready again. Do not alter .harness/check.py.',root/'agent',hook_context=root/'context.json')
gate=read_json(evidence/'gate.json');assert gate['attempts']>=2 and gate['status']=='passed' and gate['snapshot']==digest(work)
print(json.dumps({'root':str(root),'session':sid,'result':result,'gate':gate},indent=2))
