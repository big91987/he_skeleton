"""GitHub event -> durable task -> one bounded Agent turn -> human review."""
import base64
import fcntl
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

from agent import run_agent

SOURCE = Path(__file__).resolve().parent.parent
SUFFIXES = {'.html', '.css', '.js', '.json', '.svg', '.png', '.jpg', '.jpeg', '.webp', '.ico', '.txt'}


def atomic(path, value):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    tmp.replace(path)


def gh(method, path, body=None):
    token = os.environ['GH_TOKEN']
    request = urllib.request.Request('https://api.github.com/' + path,
        data=None if body is None else json.dumps(body).encode(), method=method,
        headers={'Authorization': 'Bearer ' + token, 'Accept':'application/vnd.github+json',
                 'Content-Type':'application/json', 'User-Agent':'he-skeleton'})
    with urllib.request.urlopen(request, timeout=45) as response:
        data = response.read()
        return json.loads(data) if data else None


def command(event, event_name):
    owner = event['repository']['owner']['login']
    if event['sender']['login'] != owner:
        raise PermissionError('Only repository owner can start local execution')
    if event_name == 'workflow_dispatch':
        return int(event['inputs']['task']), event['inputs'].get('instruction', '继续检查'), 'dispatch-' + os.environ['GITHUB_RUN_ID']
    if event_name == 'issues':
        issue = event['issue']
        if event.get('action') != 'opened' or not any(x['name'] == 'harness' for x in issue['labels']):
            raise ValueError('Not a harness task')
        return issue['number'], '开始处理上述需求。', 'issue-' + str(issue['id'])
    comment = event['comment']
    match = re.match(r'^/harness(?:\s+([\s\S]*))?$', comment['body'].strip())
    if not match:
        raise ValueError('Explicit /harness command required')
    return event['issue']['number'], match[1] or '继续', 'comment-' + str(comment['id'])


def clarification_only(event_name, body, instruction):
    explicit = instruction.strip().split(maxsplit=1)[0] if instruction.strip() else ''
    if explicit in {'clarify', '澄清'}:
        return True
    return event_name == 'issues' and not re.search(r'### 开始方式\s+直接实施', body or '')


def app_files(root):
    files = {}
    for p in root.rglob('*'):
        if p.is_symlink():
            raise ValueError('Symlinks are not publishable')
        if not p.is_file():
            continue
        if any(part.startswith('.') for part in p.relative_to(root).parts) or p.suffix not in SUFFIXES:
            raise ValueError('Unsupported preview file: ' + p.name)
        if p.stat().st_size > 2_000_000:
            raise ValueError('Preview file too large')
        files[p.relative_to(root).as_posix()] = p.read_bytes()
    if 'index.html' not in files or len(files) > 100 or sum(map(len, files.values())) > 10_000_000:
        raise ValueError('Preview requires index.html and must be <=100 files / 10 MB')
    return files


def publish_code(repo, branch, base_sha, files, message):
    prefix = 'repos/' + repo
    try:
        head = gh('GET', prefix + '/git/ref/heads/' + branch)['object']['sha']
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        head = base_sha
        gh('POST', prefix + '/git/refs', {'ref':'refs/heads/' + branch, 'sha':head})
    if head != base_sha:
        raise RuntimeError('Branch changed during execution; refusing to overwrite external work')
    commit = gh('GET', prefix + '/git/commits/' + head)
    old_tree = gh('GET', prefix + '/git/trees/' + commit['tree']['sha'] + '?recursive=1')
    if old_tree.get('truncated'):
        raise ValueError('Repository tree too large')
    old = {x['path']: x for x in old_tree['tree'] if x['path'].startswith('app/') and x['type'] == 'blob'}
    tree = []
    for name, data in files.items():
        path = 'app/' + name
        blob_sha = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        if old.get(path, {}).get('sha') != blob_sha:
            blob = gh('POST', prefix + '/git/blobs', {'content':base64.b64encode(data).decode(), 'encoding':'base64'})
            tree.append({'path':path, 'mode':'100644', 'type':'blob', 'sha':blob['sha']})
    for path in old.keys() - {'app/' + x for x in files}:
        tree.append({'path':path, 'mode':'100644', 'type':'blob', 'sha':None})
    if not tree:
        return head
    new_tree = gh('POST', prefix + '/git/trees', {'base_tree':commit['tree']['sha'], 'tree':tree})
    new_commit = gh('POST', prefix + '/git/commits', {'message':message, 'tree':new_tree['sha'], 'parents':[head]})
    gh('PATCH', prefix + '/git/refs/heads/' + branch, {'sha':new_commit['sha'], 'force':False})
    return new_commit['sha']


def restore_app(repo, sha, target):
    tree = gh('GET', f'repos/{repo}/git/trees/{sha}?recursive=1')
    if tree.get('truncated'):
        raise ValueError('Repository tree too large')
    for item in tree['tree']:
        path = item['path']
        if not path.startswith('app/') or item['type'] != 'blob':
            continue
        name = Path(path[4:])
        if '..' in name.parts or name.is_absolute() or item['mode'] == '120000':
            raise ValueError('Unsafe imported app path')
        if item.get('size', 0) > 2_000_000:
            raise ValueError('App file too large')
        blob = gh('GET', f'repos/{repo}/git/blobs/' + item['sha'])
        dest = target / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(base64.b64decode(blob['content']))


def experiment_context(root, branch):
    if not branch:
        return root, ''
    if not branch.startswith('codex/harness-test-'):
        raise ValueError('Invalid experiment branch')
    scope = hashlib.sha256(branch.encode()).hexdigest()[:16]
    return root / 'experiments' / scope, scope


def main():
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    task, instruction, event_id = command(event, os.environ['GITHUB_EVENT_NAME'])
    repo = os.environ['GITHUB_REPOSITORY']
    if repo != event['repository']['full_name'] or task <= 0:
        raise ValueError('Invalid repository/task')
    root = Path(os.environ['HARNESS_ROOT']).resolve()
    tools_root = root
    experiment = os.environ.get('HARNESS_EXPERIMENT', '')
    root, scope = experiment_context(root, experiment)
    session = root / 'sessions' / str(task)
    session.mkdir(parents=True, exist_ok=True)
    output = Path(os.environ['RUNNER_TEMP']) / 'harness-output'
    output.mkdir(parents=True, exist_ok=True)
    run_url = f'https://github.com/{repo}/actions/runs/' + os.environ['GITHUB_RUN_ID']
    prefix = f'repos/{repo}'
    def comment(body):
        # Every public response identifies the originating event/run.
        gh('POST', f'{prefix}/issues/{task}/comments', {'body':(('实验分支：`' + experiment + '`。继续测试请在 Actions 选择同一分支运行，不使用主线 /harness 评论入口。\n\n') if experiment else '') + body + f'\n\n[执行记录]({run_url}) · `{event_id}`'})
    with (session / 'lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state_path = session / 'state.json'
        state = json.loads(state_path.read_text()) if state_path.exists() else {'history':[], 'processed':[], 'round':0}
        if event_id in state['processed']:
            print('Event already handled')
            return
        if instruction.strip().lower() in {'stop', '停止'}:
            state['status'] = 'stopped'
            state['processed'].append(event_id)
            atomic(state_path, state)
            comment('已停止后续推进，保留任务工作区和历史。正在执行的 Job 请在 Actions 点击 Cancel。')
            return
        if instruction.strip().lower() in {'publish', '发布'}:
            if not state.get('preview') or not (root/'previews'/state['preview']/'index.html').is_file():
                raise ValueError('No saved preview to publish')
            summary = next((entry['agent']['summary'] for entry in reversed(state['history']) if 'agent' in entry), '')
            atomic(output/'result.json', {'task':task,'summary':summary,'preview':state['preview'],
                                         'pr_url':state['pr_url'],'sha':state['source_sha'],'event_id':event_id})
            state['status'] = 'preview_pending'
            state['run_id'] = os.environ['GITHUB_RUN_ID']
            state['processed'].append(event_id)
            atomic(state_path, state)
            with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
                f.write('publish=true\ntask='+str(task)+'\n')
            comment('仅重新发布已保存并检查过的预览，不调用 Agent、不修改业务代码。')
            return
        issue = gh('GET', f'{prefix}/issues/{task}')
        if issue['state'] == 'closed':
            comment('任务已关闭；请先重新打开，再继续。')
            return
        base = experiment or gh('GET', prefix)['default_branch']
        if experiment and 'pull_request' in issue:
            raise ValueError('Experiments use an Issue; PR branches are not modified')
        source_sha = gh('GET', f'{prefix}/git/ref/heads/{base}')['object']['sha']
        if 'pull_request' in issue:
            pr = gh('GET', f'{prefix}/pulls/{task}')
            if pr['head']['repo']['full_name'] != repo:
                raise PermissionError('Fork PRs are not executed locally')
            source_sha = pr['head']['sha']
            branch = pr['head']['ref']
            if branch == base:
                raise ValueError('Cannot modify default branch')
            state['pr_url'] = pr['html_url']
        else:
            branch = f'codex/test-{scope}/task-{task}' if scope else f'codex/task-{task}'
            try:
                head = gh('GET', f'{prefix}/git/ref/heads/{branch}')['object']['sha']
                if state.get('source_sha') and state['source_sha'] != head:
                    raise RuntimeError('Task branch changed outside this session')
                source_sha = head
            except urllib.error.HTTPError as error:
                if error.code != 404:
                    raise
        workspace = session / 'workspace'
        workspace.mkdir(exist_ok=True)
        app = workspace / 'app'
        if not app.exists():
            app.mkdir()
            restore_app(repo, source_sha, app)
        elif 'pull_request' in issue and state.get('source_sha') not in {None, source_sha}:
            comment('PR 分支已在外部更新。为避免覆盖持久化工作区，请新建任务接入该版本；本轮未执行。')
            return
        state['round'] += 1
        state['status'] = 'running'
        state['run_id'] = os.environ['GITHUB_RUN_ID']
        state['history'].append({'user':instruction, 'event':event_id})
        state['source_sha'] = source_sha
        atomic(state_path, state)
        comment(f'开始第 {state["round"]} 轮，恢复此任务已有工作区。完成后会回写结果；无需保持页面打开。')
        evidence = session / f'round-{state["round"]}'
        evidence.mkdir()
        try:
            prompt = ('You are implementing a small static web application in app/. Reply in Chinese. '
                'Only edit files in app/. Do not touch host files, credentials, workflow configuration, git remotes or install dependencies. '
                'No backend, no external network/CDNs. HTML/CSS/JS only; use localStorage for demo persistence. '
                'Complete basic user journeys, not isolated buttons. Keep existing accepted behavior when revising. '
                'If the user explicitly asks to clarify/inspect first or a key product choice blocks work, return needs_input with a concrete question and stop. '
                'Follow the latest user feedback: if an earlier request to ask first has already been answered in history, continue implementation instead of asking again. '
                'Otherwise implement and return ready. Never claim tests ran; the harness will test separately. '
                'Also create app/acceptance.json: an array of browser steps proving the requested main user journey. '
                'The array is flat: [{"action":"fill","label":"任务","value":"测试任务"},{"action":"click","role":"button","name":"新增"}]. No name/steps wrapper. '
                'Each step has action fill/click/visible/absent/reload. Locate using label, or role+name, or exact text; fill has value. '
                'Use accessible labels. This plan is implementation-authored evidence, not independent acceptance.\n'
                + 'Original task:\n' + issue['title'] + '\n' + (issue['body'] or '')
                + '\nDurable history:\n' + json.dumps(state['history'], ensure_ascii=False))
            read_only = clarification_only(os.environ['GITHUB_EVENT_NAME'], issue['body'], instruction)
            if read_only:
                prompt += ('\nCURRENT STAGE: CLARIFICATION ONLY. You must not implement or edit files. '
                           'Return needs_input and the specific question the user requested, or a concise scope confirmation. '
                           'This is a read-only stage enforced by the host. Do not treat the generic start instruction as a user answer.')
            original_app = app_files(app) if read_only else None
            result = None
            for attempt in range(3):
                result = run_agent(workspace, prompt, evidence / f'agent-{attempt + 1}', read_only=read_only)
                if read_only and app_files(app) != original_app:
                    raise RuntimeError('Read-only clarification modified app files')
                if result['status'] == 'needs_input':
                    break
                app_files(app)
                plan = app / 'acceptance.json'
                if not plan.exists() or not json.loads(plan.read_text()):
                    prompt += '\nCheck failed: write a nonempty acceptance.json proving the main interaction.'
                    continue
                browser_env = {'PATH':os.environ['PATH'], 'HOME':os.environ['HOME'],
                               'NODE_PATH':str(tools_root/'tools/node_modules')}
                test = subprocess.run(['node', str(SOURCE/'harness/browser.cjs'), str(app), str(evidence), str(plan)],
                    capture_output=True, text=True, env=browser_env, timeout=90)
                if test.returncode == 0:
                    break
                prompt += '\nReal browser check failed. Repair app and preserve requirements:\n' + test.stderr[-5000:]
            else:
                raise RuntimeError('Browser checks still fail after 3 bounded attempts')
            state['history'].append({'agent':result})
            state['processed'].append(event_id)
            if result['status'] == 'needs_input':
                state['status'] = 'waiting_input'
                atomic(state_path, state)
                comment(result['summary'] + '\n\n**需要你反馈：**\n' + result['question'] + '\n\n回复 `/harness 你的意见` 即可继续；本轮执行现在结束。')
                return
            files = app_files(app)
            sha = publish_code(repo, branch, source_sha, files, f'Harness task #{task}, round {state["round"]}')
            state['source_sha'] = sha
            if not state.get('pr_url'):
                existing = gh('GET', f'{prefix}/pulls?head=' + urllib.parse.quote(repo.split('/')[0]+':'+branch) + '&state=open')
                state['pr_url'] = existing[0]['html_url'] if existing else f'https://github.com/{repo}/compare/{base}...{branch}?expand=1'
            preview_rel = f'task-{task}/round-{state["round"]}'
            preview = root/'previews'/preview_rel
            preview.mkdir(parents=True, exist_ok=True)
            for name, data in files.items():
                dest = preview/name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
            for name in ['screenshot.png', 'mobile.png', 'browser.json']:
                shutil.copy2(evidence/name, preview/name)
            links = sorted((root/'previews').glob('task-*/round-*/index.html'))
            (root/'previews/index.html').write_text('<!doctype html><meta charset="utf-8"><title>Harness previews</title><h1>实验预览</h1><p>静态网页实验；每一轮链接固定，旧版本不会被新版本覆盖。</p><ul>' + ''.join(
                f'<li><a href="{p.relative_to(root/"previews").as_posix()}">{html.escape(str(p.parent.relative_to(root/"previews")))}</a></li>' for p in links) + '</ul>')
            # Only safe preview files and public result go into uploaded artifacts.
            atomic(output/'result.json', {'task':task,'summary':result['summary'], 'preview':preview_rel,
                                         'pr_url':state['pr_url'], 'sha':sha, 'event_id':event_id})
            state['status'] = 'preview_pending'
            state['preview'] = preview_rel
            atomic(state_path, state)
            with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
                f.write('publish=true\n')
                f.write('task=' + str(task) + '\n')
            comment(result['summary'] + f'\n\n浏览器路径检查通过，已保存任务分支。[查看改动／创建 PR]({state["pr_url"]})。预览交付完成后另附结果（测试分支使用运行附件）。尚未通过人工验收。')
        except Exception as error:
            state['status'] = 'blocked'
            atomic(state_path, state)
            comment('本轮未完成，工作区和上下文已保留。错误类型：`' + type(error).__name__ + '`。请查看执行日志；处理后回复 `/harness 重试`。')
            raise


if __name__ == '__main__':
    def interrupted(signum, frame):
        raise KeyboardInterrupt('Runner interrupted')
    signal.signal(signal.SIGTERM, interrupted)
    main()
