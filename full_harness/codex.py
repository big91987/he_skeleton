"""One persistent task session; independent reviewer sessions; vetted native Stop hook."""
import json
import os
from pathlib import Path
import shlex
import sys
import uuid

from .common import clean_env, read_json, run_process, write_json
from .skills import configure as configure_skills

RESULT_SCHEMA = {'type':'object','additionalProperties':False,'properties':{
    'status':{'type':'string','enum':['ready','needs_input','blocked']},
    'summary':{'type':'string'},'question':{'type':'string'},
    'artifacts':{'type':'array','items':{'type':'string'}}},
    'required':['status','summary','question','artifacts']}
REVIEW_SCHEMA = {'type':'object','additionalProperties':False,'properties':{
    'status':{'type':'string','enum':['passed','changes','needs_input','blocked']},
    'summary':{'type':'string'},'question':{'type':'string'},
    'return_stage':{'type':'string','enum':['requirements','design','development']},
    'findings':{'type':'array','items':{'type':'string'}}},
    'required':['status','summary','question','return_stage','findings']}


def runtime_home(home):
    """Reuse machine authentication without copying secrets into a project or artifact."""
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    auth = Path(os.environ.get('CODEX_AUTH_HOME',str(Path.home()/'.codex')))/'auth.json'
    target = home/'auth.json'
    if not target.exists():
        if not auth.is_file():
            raise RuntimeError('Runner requires a pre-authenticated Codex auth.json; no login is performed by a task')
        target.symlink_to(auth)
    return home


def invoke(source, workspace, session_dir, prompt, evidence, session_id=None, hook_context=None, review=False, timeout_override=None, schema_override=None, skills=None):
    if (workspace/'.codex').exists():
        raise ValueError('This initial runtime requires project .codex configuration to be reviewed and removed from the execution workspace before enabling the managed hook')
    evidence.mkdir(parents=True, exist_ok=False)
    home = runtime_home(session_dir/('review-home' if review else 'codex-home'))
    schema = schema_override or (REVIEW_SCHEMA if review else RESULT_SCHEMA)
    write_json(evidence/'schema.json',schema)
    (evidence/'prompt.txt').write_text(prompt)
    # Project and user config must not add arbitrary hooks. The only hook below is
    # assembled by the controller from its fixed execution revision.
    config = 'approval_policy="never"\nsandbox_mode='+json.dumps('read-only' if review else 'workspace-write')+'\n'
    config += 'model_provider="harness_http"\n[model_providers.harness_http]\nname="OpenAI HTTPS"\nwire_api="responses"\nrequires_openai_auth=true\nsupports_websockets=false\n'
    if hook_context:
        cmd = shlex.join([sys.executable,str(source/'full_harness/stop_hook.py'),str(hook_context)])
        config += '\n[[hooks.Stop]]\n[[hooks.Stop.hooks]]\ntype="command"\ncommand='+json.dumps(cmd)+'\ntimeout=600\n'
    if (home/'hooks.json').exists():
        raise ValueError('Unexpected unmanaged hook configuration')
    configure_skills(home, workspace, source, skills or [], config, evidence)
    argv = ['codex','exec'] + (['resume',session_id] if session_id else [])
    argv += ['--skip-git-repo-check','--json','--output-schema',str(evidence/'schema.json'),
             '--output-last-message',str(evidence/'result.json')]
    if hook_context:
        # Safe only for this generated config and controlled workspace; never
        # applied to arbitrary user/project hook sources.
        argv += ['--dangerously-bypass-hook-trust']
    argv += ['-']
    env = clean_env(); env['CODEX_HOME']=str(home)
    timeout = read_json(hook_context)['config']['agent_timeout'] if hook_context else 600
    if review: timeout = timeout_override or 480
    log = evidence/'agent.jsonl'
    code = None
    try:
        code = run_process(argv,workspace,env,log,timeout,prompt)
    finally:
        ids=[]
        if log.exists():
            for line in log.read_text().splitlines():
                try: item=json.loads(line)
                except ValueError: continue
                if item.get('type')=='thread.started':ids.append(item['thread_id'])
        if ids:
            uuid.UUID(ids[0])
            write_json(evidence/'session.json',{'session_id':ids[0],'previous':session_id})
            if not review:write_json(session_dir/'codex-session.json',{'session_id':ids[0]})
    if not ids or (session_id and ids[0] != session_id):
        raise RuntimeError('Codex session continuity could not be verified')
    if code != 0 or not (evidence/'result.json').exists():
        raise RuntimeError('Codex execution failed; see private task log')
    result=read_json(evidence/'result.json')
    if set(result)!=set(schema['required']) or result['status'] not in schema['properties']['status']['enum']:
        raise ValueError('Invalid Agent result')
    if any(not isinstance(result[k],str) for k in ['status','summary','question']):
        raise ValueError('Invalid result text')
    if result['status']=='needs_input' and not result['question'].strip():
        raise ValueError('Missing clarification question')
    if schema_override is not None:
        return result,ids[0]
    array_key = 'findings' if review else 'artifacts'
    if not isinstance(result[array_key],list) or not all(isinstance(x,str) for x in result[array_key]):
        raise ValueError('Invalid result array')
    if review and result['return_stage'] not in ['requirements','design','development']:
        raise ValueError('Invalid review return stage')
    return result,ids[0]
