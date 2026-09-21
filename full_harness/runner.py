#!/usr/bin/env python3
"""Independent staged workflow. Task state and native sessions remain on one Runner."""
import argparse
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from full_harness.common import STAGES, configuration, controls, digest, files, read_json, relative_file, write_json, run_process, clean_env
from full_harness.codex import invoke
from full_harness.stop_hook import review_prompt
from full_harness.router import classify


def api(repo,path,method='GET',data=None):
    argv=['gh','api','repos/'+repo+'/'+path,'--method',method]
    if data is not None:argv+=['--input','-']
    result=subprocess.run(argv,input=json.dumps(data) if data is not None else None,capture_output=True,text=True,timeout=90)
    if result.returncode:raise RuntimeError('GitHub API failed: '+path+' '+result.stderr[-800:])
    return json.loads(result.stdout) if result.stdout.strip() else None


def output(name,value):
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write(name+'='+str(value)+'\n')


def event_input(event,repo,actor,event_name):
    owner=repo.split('/')[0]
    if actor!=owner or os.environ.get('GITHUB_TRIGGERING_ACTOR',actor)!=owner:
        raise ValueError('Only repository owner may start or resume this local Runner')
    if event_name=='workflow_dispatch':
        inputs=event.get('inputs',{})
        task=inputs.get('task','');instruction=inputs.get('instruction','')
    elif event_name=='issues' and event.get('action') in {'opened','labeled'}:
        if 'harness-full' not in [x['name'] for x in event['issue']['labels']]:raise ValueError('Missing full workflow label')
        task=event['issue']['number'];instruction=''
    elif event_name=='issue_comment' and event.get('action')=='created':
        body=event['comment']['body']
        if not re.match(r'^/develop(?:\s|$)',body):raise ValueError('Not a full workflow command')
        task=event['issue']['number'];instruction=body[len('/develop'):].strip()
    else:raise ValueError('Unsupported entry event')
    if not str(task).isdigit() or int(task)<1:raise ValueError('Task must be an existing Issue number')
    return int(task),instruction


def new_state(source,session,task,repo,sha,branch,runner):
    cfg=configuration(source)
    if (source/'.codex').exists():raise ValueError('Unreviewed project .codex config is not supported by this runtime')
    workspace=session/'workspace'
    if workspace.exists():raise ValueError('Partial initialization retained; inspect before restarting')
    workspace.mkdir()
    for name,data in files(source).items():
        dest=relative_file(workspace,name);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
        dest.chmod((source/name).stat().st_mode & 0o777)
    git_env={k:v for k,v in os.environ.items() if not k.startswith(('GIT_', 'GH_'))}
    for argv in [['init','-q'],['add','.'],['-c','user.name=Harness','-c','user.email=harness@example.invalid','commit','-q','--allow-empty','-m','Task baseline']]:
        subprocess.run(['git','-c','core.hooksPath=/dev/null',*argv],cwd=workspace,env=git_env,check=True,capture_output=True)
    state={'version':1,'repo':repo,'task':task,'baseline':sha,'branch':branch,'runner':runner,
           'stage':'entry','status':'running','completed':{},'turn':0,'config':cfg,
           'controls':controls(workspace),'baseline_files':{n:hashlib.sha256(b).hexdigest() for n,b in files(workspace).items()},
           'baseline_modes':{n:((workspace/n).stat().st_mode & 0o111) for n in files(workspace)},'history':[]}
    return state


def begin(state,instruction,sha,runner,run_id):
    if state['runner']!=runner:raise ValueError('Persistent state belongs to another Runner')
    if state['baseline']!=sha:raise ValueError('Base revision changed: reconcile in a new task before continuing; previous evidence cannot be reused silently')
    if state['status']=='delivered':raise ValueError('This task has delivered; start a new Issue for the next iteration')
    if state['status'] in {'needs_input','blocked','waiting_review'}:
        token=state['reply_token']
        if not instruction.startswith(token+' '):raise ValueError('Reply with /develop '+token+' followed by your answer or recovery instruction')
        instruction=instruction[len(token):].strip()
    if state['status']=='waiting_review':
        state['stage']='entry'
        for stage in ['implementation','verification','review','delivery']:state['completed'].pop(stage,None)
    state.update(instruction=instruction,status='running',run_id=run_id)
    state.pop('reply_token',None)
    state.pop('reason',None)


def pause(state,status,reason):
    state.update(status=status,reason=reason,reply_token=uuid.uuid4().hex[:10])


def prompt_for(source,state,stage):
    cfg=state['config'];spec=cfg['stages'][stage]
    skills=[]
    for name in spec['skills']:
        p=source/'full_harness/skills'/name/'SKILL.md'
        skills.append('Skill 原位置（相对引用从此解析）：'+str(p)+'\n'+p.read_text())
    artifact=spec['artifact'].replace('{task}',str(state['task']['number']))
    packet={'task':state['task'],'stage':stage,'instruction':state.get('instruction',''),
            'project_entries':cfg['entries'],'completed':state['completed'],'routing':state.get('routing'),
            'handoff_artifact':artifact,'checks':cfg.get('checks',[]),'feedback':state.get('feedback','')}
    return ('你在持久化的项目任务会话里工作。本次只交付指定阶段。先阅读项目入口和引用的现状、约束与实际代码，再执行适用 Skill。\n'
        '已有 PRD、原型或代码可以直接复用，用本阶段交接记录说明来源、适用范围和缺口，不机械重写。'
        '需求阶段澄清目标、用户完整主线及 AC；设计阶段覆盖必要接口/数据/迁移/兼容与取舍；规划阶段拆可验收任务；实现阶段逐项实现并真实验证。'
        '低风险小改允许简短文档；平台专用 Skill 只在平台项目适用。需要用户做产品或架构决定时返回 needs_input 和清晰问题；可自行消除的问题继续做。'
        '不得虚构用户决定、凭直接改数据库/伪造数据证明产品入口可用。不得修改受保护的执行配置、Skills 或 AGENTS.md。'
        '把可共享决策和现状更新到项目文档，私有对话不能作为其他任务的唯一知识来源。'
        '阶段达到可交接状态后返回 ready；环境确实无法推进返回 blocked。Stop Hook 会检查并把失败反馈到本会话，ready 本身不代表通过。\n'
        +json.dumps(packet,ensure_ascii=False,indent=2)+'\n\n'+'\n\n'.join(skills))


def checkpoint(session,state):
    write_json(session/'state.json',state)
    if os.environ.get('GITHUB_ACTIONS')=='true':
        report(session,state)
        write_json(session/'state.json',state)


def recover_session(session):
    """Recover a thread.started checkpoint if cancellation killed the controller."""
    saved=session/'codex-session.json'
    sid=read_json(saved)['session_id'] if saved.exists() else None
    logs=sorted((session/'turns').glob('*/agent/agent.jsonl'),key=lambda p:int(p.parents[1].name))
    for log in reversed(logs):
        for line in log.read_text().splitlines():
            try:item=json.loads(line)
            except ValueError:continue
            if item.get('type')=='thread.started':
                found=item['thread_id'];uuid.UUID(found)
                if sid and sid!=found:raise ValueError('Native session checkpoint conflicts with execution history')
                write_json(saved,{'session_id':found});return found
    if sid:return sid
    if any((session/'codex-home/sessions').rglob('*.jsonl')):
        raise ValueError('Native sessions exist without a verified task mapping; inspect retained state')
    return None


def next_stage(state,after=None):
    start=STAGES.index(after)+1 if after else 0
    for stage in STAGES[start:]:
        if stage not in state['completed']:return stage
    return 'delivery'


def assess_entry(source,session,state):
    state['turn']+=1;checkpoint(session,state)
    result=classify(source,session/'workspace',session,state,session/'turns'/str(state['turn'])/'routing')
    state['routing']=result
    if result['status']!='ready':
        pause(state,result['status'],result['question'] or result['summary']);return
    # Assessment can invalidate earlier outcomes when feedback changes the task.
    state['completed']={}
    for item in result['decisions']:
        if item['action']!='run':
            state['completed'][item['stage']]={'mode':item['action'],'summary':item['reason'],
                'evidence':item['evidence_hashes']}
    state['stage']=next_stage(state)


def verify_stage(source,session,state,attempt=0):
    if attempt>=state['config']['max_attempts']:
        pause(state,'blocked','Verification repair limit reached');return
    workspace=session/'workspace'
    checks=[c for c in state['config'].get('checks',[]) if set(c.get('stages',['implementation'])) & {'implementation','verification'}]
    if not checks:raise ValueError('No Owner-configured verification checks; routing cannot bypass verification')
    if controls(workspace)!=state['controls']:raise ValueError('Execution controls changed')
    before=digest(workspace)
    impl=state['completed'].get('implementation',{})
    # Reuse an exact matching, controller-produced gate; never a model claim.
    gate_path=session/'turns'/str(impl.get('turn','missing'))/'gate.json'
    gate=read_json(gate_path) if gate_path.exists() else {}
    only_implementation=all('implementation' in c.get('stages',['implementation']) for c in checks)
    if only_implementation and gate.get('status')=='passed' and gate.get('snapshot')==before:
        outcomes=gate['checks']
    else:
        state['turn']+=1;checkpoint(session,state)
        evidence=session/'turns'/str(state['turn']);evidence.mkdir(parents=True)
        outcomes=[]
        for i,check in enumerate(checks):
            log=evidence/f'check-{i}.log';env=clean_env()
            if os.environ.get('NODE_PATH'):env['NODE_PATH']=os.environ['NODE_PATH']
            argv=[x.replace('{workspace}',str(workspace)).replace('{evidence}',str(evidence)) for x in check['argv']]
            code=run_process(argv,relative_file(workspace,check.get('cwd','.')),env,log,state['config']['check_timeout'])
            outcomes.append({'name':check['name'],'code':code,'log':log.name})
            if code in (124,125):raise ValueError('Verification environment unavailable: '+check['name'])
            if code:
                state['feedback']=check['name']+' failed: '+log.read_text()[-6000:]
                state['completed'].pop('implementation',None)
                # Real check failure goes into the existing bounded implementation
                # loop, not back to the human just because code was supplied.
                work_stage(source,session,state,'implementation')
                if state['status']!='running':return
                # A verification-only failing check must also be included in the
                # implementation gate, so repaired code is checked before return.
                return verify_stage(source,session,state,attempt+1)
        if digest(workspace)!=before:raise ValueError('Verification changed project files; evidence invalidated')
    state['completed']['verification']={'summary':'Owner-configured checks passed','checks':outcomes,'snapshot':digest(workspace)}
    state['stage']='review'


def work_stage(source,session,state,stage):
    workspace=session/'workspace';state['turn']+=1
    state['stage']=stage
    checkpoint(session,state)
    print('Executing stage: '+stage,flush=True)
    evidence=session/'turns'/str(state['turn']);evidence.mkdir(parents=True)
    context={'source':str(source),'workspace':str(workspace),'session':str(session),'evidence':str(evidence),
             'task':state['task'],'instruction':state.get('instruction',''),'stage':stage,'config':state['config'],
             'controls':state['controls'],'baseline':state['baseline'],
             'deadline_monotonic':time.monotonic()+state['config']['agent_timeout'],'node_path':os.environ.get('NODE_PATH','')}
    write_json(evidence/'context.json',context)
    sid=recover_session(session)
    result,sid=invoke(source,workspace,session,prompt_for(source,state,stage),evidence/'agent',sid,evidence/'context.json')
    gate=read_json(evidence/'gate.json') if (evidence/'gate.json').exists() else {'status':'blocked','reason':'Native Stop Hook did not supply a verified gate'}
    state['history'].append({'stage':stage,'turn':state['turn'],'session_id':sid,'agent':result['status'],'gate':gate['status']})
    if result['status']!='ready':
        pause(state,result['status'],result['question'] or result['summary']);return
    if gate['status']!='passed':
        pause(state,gate['status'] if gate['status'] in {'needs_input','blocked'} else 'blocked',gate.get('reason','Gate did not pass'));return
    if gate.get('snapshot')!=digest(workspace) or controls(workspace)!=state['controls']:
        pause(state,'blocked','Workspace changed after verification');return
    artifact=gate['artifact'];path=relative_file(workspace,artifact)
    state['completed'][stage]={'artifact':artifact,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                               'summary':result['summary'],'checks':gate.get('checks',[]),'turn':state['turn']}
    state['stage']=next_stage(state,stage)
    state['feedback']=''


def review_stage(source,session,state):
    workspace=session/'workspace'
    # The independent review may invalidate an earlier stage. Repairs are bounded
    # and use the original builder session, never the reviewer session.
    if state['completed'].get('verification',{}).get('snapshot')!=digest(workspace):
        verify_stage(source,session,state)
        if state['status']!='running':return
    for attempt in range(state['config']['max_attempts']):
        state['turn']+=1;state['stage']='review';checkpoint(session,state)
        print('Executing independent review',flush=True)
        evidence=session/'turns'/str(state['turn'])
        context={'task':state['task'],'config':state['config'],'baseline':state['baseline'],
                 'instruction':state.get('instruction',''),'routing':state.get('routing'),'check_results':state['completed'].get('verification',{}).get('checks',[])}
        before=digest(workspace)
        result,sid=invoke(source,workspace,session,review_prompt(source,workspace,context,'review'),evidence,review=True,timeout_override=state['config']['review_timeout'])
        state['history'].append({'stage':'review','turn':state['turn'],'session_id':sid,'gate':result['status']})
        if before!=digest(workspace):pause(state,'blocked','Workspace changed during independent review');return
        if result['status']=='passed':
            state['completed']['review']={'summary':result['summary'],'snapshot':before,'turn':state['turn']}
            state['stage']='delivery';return
        if result['status'] in {'needs_input','blocked'}:
            pause(state,result['status'],result['question'] or result['summary']);return
        state['feedback']=result['summary']+'\n'+'\n'.join(result['findings'])
        start=STAGES.index(result['return_stage'])
        for stage in STAGES[start:]:state['completed'].pop(stage,None)
        state['stage']=STAGES[start]
        for stage in STAGES[start:4]:
            work_stage(source,session,state,stage)
            if state['status']!='running':return
        verify_stage(source,session,state)
        if state['status']!='running':return
    pause(state,'blocked','独立评审整改达到上限。'+state.get('feedback',''))


def deliver(session,state):
    workspace=session/'workspace';repo=state['repo']
    if state['completed'].get('review',{}).get('snapshot')!=digest(workspace):raise ValueError('Independent review no longer matches delivery contents')
    if controls(workspace)!=state['controls']:raise ValueError('Execution controls changed')
    base=api(repo,'commits/'+state['branch'])
    if base['sha']!=state['baseline']:raise ValueError('Base branch advanced; delivery requires reconciliation')
    current=files(workspace);old=state['baseline_files'];tree=[]
    for name in sorted(set(current)|set(old)):
        if name in current and hashlib.sha256(current[name]).hexdigest()==old.get(name) and (workspace/name).stat().st_mode & 0o111 == state.get('baseline_modes',{}).get(name):continue
        item={'path':name,'mode':'100755' if name in current and (workspace/name).stat().st_mode & 0o111 else '100644','type':'blob'}
        if name not in current:item['sha']=None
        else:item['sha']=api(repo,'git/blobs','POST',{'encoding':'base64','content':base64.b64encode(current[name]).decode()})['sha']
        tree.append(item)
    if not tree:
        state['completed']['delivery']={'summary':'Existing code verified; no new changes to commit'}
        pause(state,'waiting_review','已有材料验证完成，无新增代码改动；请查看评审与验证结果。')
        return
    branch='codex/full-task-'+str(state['task']['number'])
    snapshot=digest(workspace)
    if state.get('delivery_snapshot')!=snapshot:
        refs=api(repo,'git/matching-refs/heads/'+branch)
        existing=[x for x in refs if x['ref']=='refs/heads/'+branch]
        previous=state.get('delivery_commit')
        if previous:
            if not existing or existing[0]['object']['sha']!=previous:raise ValueError('Delivery branch changed externally')
        elif existing:raise ValueError('Delivery branch already exists; inspect before retrying')
        t=api(repo,'git/trees','POST',{'base_tree':base['commit']['tree']['sha'],'tree':tree})
        commit=api(repo,'git/commits','POST',{'message':'Deliver #'+str(state['task']['number'])+': '+state['task']['title'],'tree':t['sha'],'parents':[previous or state['baseline']]})
        state.update(delivery_commit=commit['sha'],delivery_parent=previous,delivery_snapshot=snapshot)
        write_json(session/'state.json',state)
    commit=state['delivery_commit']
    refs=api(repo,'git/matching-refs/heads/'+branch)
    existing=[x for x in refs if x['ref']=='refs/heads/'+branch]
    if existing and existing[0]['object']['sha']!=commit:
        if existing[0]['object']['sha']!=state.get('delivery_parent'):raise ValueError('Delivery branch changed externally')
        api(repo,'git/refs/heads/'+branch,'PATCH',{'sha':commit,'force':False})
    if not existing:api(repo,'git/refs','POST',{'ref':'refs/heads/'+branch,'sha':commit})
    pulls=api(repo,'pulls?state=open&head='+repo.split('/')[0]+':'+branch)
    pr=pulls[0] if pulls else api(repo,'pulls','POST',{'title':state['task']['title'],'head':branch,'base':state['branch'],'draft':True,
        'body':'Closes #'+str(state['task']['number'])+'\n\n独立完整流程交付。各阶段记录与验证范围见 Issue 交付卡片。请审查后合入。'})
    state.update(pr_url=pr['html_url'],pr_number=pr.get('number'))
    pause(state,'waiting_review','已创建或更新待审 PR；可在 GitHub 审查合入，或回复具体修改意见继续当前任务。')
    state['completed']['delivery']={'summary':pr['html_url']}


def report(session,state):
    run_url='https://github.com/'+state['repo']+'/actions/runs/'+str(state.get('run_id',''))
    rows=['<!-- harness-full -->','### 完整研发流程','#'+str(state['task']['number'])+' · '+state['status'],
          '| 阶段 | 状态 | 产物 / 说明 |','|---|---|---|']
    for stage in STAGES:
        done=state['completed'].get(stage)
        status=({'reuse':'复用已有产物','not_applicable':'无需执行'}.get(done.get('mode'),'已检查')) if done else (state['status'] if stage==state['stage'] else '尚未完成')
        detail=(done or {}).get('artifact') or (done or {}).get('summary','')
        rows.append('| '+stage+' | '+status+' | '+str(detail).replace('|','/').replace('\n',' ')[:600]+' |')
    if state.get('routing'):
        rows+=['','**入口判别：** '+state['routing']['summary']]
        for item in state['routing'].get('decisions',[]):
            rows+=['- '+item['stage']+' · '+item['action']+'：'+item['reason']+'；依据：'+', '.join(item['evidence'])]
    for stage in STAGES[:4]:
        name=state['config']['stages'][stage]['artifact'].replace('{task}',str(state['task']['number']))
        path=relative_file(session/'workspace',name)
        if path.is_file() and path.suffix=='.md':
            rows+=['','<details><summary>'+stage+' · '+name+'</summary>','',path.read_text()[:5000],'','</details>']
    if state.get('reason'):rows+=['',state['reason'][:8000]]
    if state.get('reply_token'):rows+=['','回复：`/develop '+state['reply_token']+' 你的回答或恢复说明`']
    if state.get('pr_url'):rows+=['','交付 PR：'+state['pr_url']]
    rows+=['','[查看本次流水线及各阶段下载包]('+run_url+')。等待澄清不代表交付完成。']
    body='\n'.join(rows)
    for private_path in [str(session),str(Path.home())]:
        body=body.replace(private_path,'<private-runtime>')
    public=Path(os.environ.get('FULL_PUBLIC',str(session/'public')));public.mkdir(parents=True,exist_ok=True)
    (public/'status.md').write_text(body)
    # Publish only declared Markdown handoff artifacts, never sessions or prompts.
    for stage in STAGES[:4]:
        artifact=state['config']['stages'][stage]['artifact'].replace('{task}',str(state['task']['number']))
        path=relative_file(session/'workspace',artifact)
        if path.is_file() and path.suffix=='.md':
            dest=public/stage/path.name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(path.read_bytes())
    output('public',str(public))
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as f:f.write(body+'\n')
    if state.get('comment_id'):api(state['repo'],'issues/comments/'+str(state['comment_id']),'PATCH',{'body':body})
    else:
        comment=api(state['repo'],'issues/'+str(state['task']['number'])+'/comments','POST',{'body':body})
        state['comment_id']=comment['id']


def main():
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['entry',*STAGES,'report'])
    args=parser.parse_args();source=Path(__file__).resolve().parents[1]
    event=read_json(os.environ['GITHUB_EVENT_PATH']);repo=os.environ['GITHUB_REPOSITORY']
    number,instruction=event_input(event,repo,os.environ['GITHUB_ACTOR'],os.environ['GITHUB_EVENT_NAME'])
    ref=os.environ['GITHUB_REF']
    if not ref.startswith('refs/heads/'):raise ValueError('Only same-repository branch executions are supported')
    branch=ref[len('refs/heads/'):];sha=os.environ['GITHUB_SHA']
    scope=hashlib.sha256((repo+'\0'+branch).encode()).hexdigest()[:16]
    storage=Path(os.environ['FULL_STATE_ROOT'])
    if not storage.is_absolute() or storage.resolve().is_relative_to(source.resolve()):raise ValueError('State root must be absolute and outside checkout')
    session=storage.resolve()/scope/str(number)
    session.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (session/'lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        state_path=session/'state.json';state=read_json(state_path) if state_path.exists() else None
        if args.stage=='entry':
            issue=api(repo,'issues/'+str(number))
            if 'pull_request' in issue:raise ValueError('Use an Issue; supply existing branch or PR as task context')
            task={'number':number,'title':issue['title'],'body':issue.get('body') or ''}
            if state is None:state=new_state(source,session,task,repo,sha,branch,os.environ['RUNNER_NAME'])
            elif task!=state['task']:raise ValueError('Issue baseline edited; provide changes as a version-bound reply or start a new task')
            if state.get('pr_number'):
                pr=api(repo,'pulls/'+str(state['pr_number']))
                if pr.get('merged_at') or pr.get('state')=='closed':raise ValueError('Delivery PR is merged or closed; use a new Issue for another iteration')
            begin(state,instruction,sha,os.environ['RUNNER_NAME'],os.environ['GITHUB_RUN_ID'])
        else:
            if state is None:raise ValueError('Task state is absent on this Runner; no silent session reset')
            if state['run_id']!=os.environ['GITHUB_RUN_ID']:raise ValueError('Run checkpoint does not match')
            if state['runner']!=os.environ['RUNNER_NAME']:raise ValueError('This workflow must run on its original persistent Runner')
        try:
            if args.stage=='entry' and state['status']=='running' and state['stage']=='entry':
                assess_entry(source,session,state)
            if state['status']=='running' and args.stage==state['stage']:
                if args.stage in STAGES[:4]:work_stage(source,session,state,args.stage)
                elif args.stage=='verification':verify_stage(source,session,state)
                elif args.stage=='review':review_stage(source,session,state)
                elif args.stage=='delivery':deliver(session,state)
        except Exception as error:
            pause(state,'blocked',str(error))
        finally:write_json(state_path,state)
        try:report(session,state)
        finally:write_json(state_path,state)
        output('continue','true' if state['status']=='running' else 'false')
        if args.stage=='entry':
            for stage in STAGES:
                output('run_'+stage,'true' if state['status']=='running' and stage not in state['completed'] else 'false')
        output('task',number)
        output('status',state['status'])
        if state['status']=='blocked' and args.stage!='report':raise SystemExit(1)


if __name__=='__main__':main()
