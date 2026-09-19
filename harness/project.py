"""Project-owned requirements and optional verification; no product type default."""
import json
from pathlib import Path

IGNORED = {'.git', '__pycache__', 'node_modules', '.venv', 'venv', '.pytest_cache'}
PROTECTED = {'.github', 'harness', 'harness-project.json', 'harness-upstream.json'}


def files(root):
    result = {}
    for path in root.rglob('*'):
        parts = path.relative_to(root).parts
        if any(part in IGNORED for part in parts):
            continue
        if path.is_symlink():
            raise ValueError('Symlinks require an explicit project import policy')
        if not path.is_file():
            continue
        if path.name == '.env' or path.name.startswith('.env.') and path.name != '.env.example' or path.suffix in {'.pem', '.key'}:
            raise ValueError('Potential credential file must not be published: ' + str(path.relative_to(root)))
        if path.stat().st_size > 2_000_000:
            raise ValueError('File exceeds current import limit')
        result[path.relative_to(root).as_posix()] = path.read_bytes()
    if len(result) > 2000 or sum(map(len, result.values())) > 50_000_000:
        raise ValueError('Project exceeds current workspace limit')
    return result


def settings(source):
    path = source / 'harness-project.json'
    value = json.loads(path.read_text()) if path.exists() else {}
    if set(value) - {'instructions', 'verification'}:
        raise ValueError('Unknown project configuration field')
    if not isinstance(value.get('instructions', ''), str):
        raise ValueError('Project instructions must be text')
    verification = value.get('verification')
    if verification is not None:
        if not isinstance(verification, dict) or verification.get('kind') != 'static-browser':
            raise ValueError('Requested verifier is not installed; do not substitute a web product')
        if set(verification) - {'kind', 'root'}:
            raise ValueError('Unknown verification field')
        root = verification.get('root')
        if not isinstance(root, str) or not root or Path(root).is_absolute() or '..' in Path(root).parts:
            raise ValueError('Verification root must be a project-relative directory')
        if root.split('/')[0] in PROTECTED:
            raise ValueError('Verification root cannot contain Harness control files')
    return value


def check_control_changes(before, after):
    for name in before.keys() | after.keys():
        if name.split('/')[0] in PROTECTED and before.get(name) != after.get(name):
            raise ValueError('Task cannot modify trusted Harness configuration: ' + name)


def prompt(issue, history, config):
    text = ("Work on the user's project in the current workspace. Reply in Chinese. "
            'Read AGENTS.md, existing requirements, acceptance criteria, designs and source before changing them. '
            'The user and accepted project decisions determine the product type and technology stack. '
            'Do not turn a backend, CLI, library, desktop application or document task into a web page. '
            'Do not invent infrastructure or claim missing capabilities are available. '
            'If a product decision or missing environment blocks the task, return needs_input with a concrete question. '
            'Otherwise implement the requested scope and return ready; ready means ready for verification, not accepted. '
            'Respect existing behavior. Do not access host credentials or modify Harness control files. '
            'Do not install dependencies or change external services without explicit task authorization. '
            'Report tests actually performed and tests not run separately.\n')
    text += 'Project instructions:\n' + config.get('instructions', '')
    if config.get('verification'):
        root = config['verification']['root']
        text += ('\nThis project explicitly enables static-browser verification at ' + root + '. '
                 'Create ' + root + '/acceptance.json as a flat array of steps. '
                 'Actions: fill/click/visible/absent/reload. Select via label, role+name, or exact text; fill includes value. '
                 'No name/steps wrapper. This implementation-authored plan does not replace independent acceptance.\n')
    else:
        text += '\nNo automatic verifier is configured. Do not invent a passed verification result or add a web page to satisfy the harness.\n'
    return text + '\nTask:\n' + issue['title'] + '\n' + (issue.get('body') or '') + '\nHistory:\n' + json.dumps(history, ensure_ascii=False)
