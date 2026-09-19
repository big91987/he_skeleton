#!/usr/bin/env python3
"""Upgrade pinned Harness tools; seed project-owned templates only on first install."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import subprocess

MANAGED = ['harness/agent.py', 'harness/project.py', 'harness/loop.py', 'harness/browser.cjs', 'harness/delivery.py']
TEMPLATES = {'.github/workflows/harness.yml': 'templates/.github/workflows/harness.yml',
             '.github/ISSUE_TEMPLATE/task.yml': 'templates/.github/ISSUE_TEMPLATE/task.yml'}


def template_diff(destination, contents):
    """Compare only; adopting a template is an explicit Owner edit."""
    for name in TEMPLATES:
        path = destination / name
        if not path.resolve().is_relative_to(destination.resolve()):
            raise ValueError('Template path escapes destination')
        current = path.read_text() if path.exists() else ''
        print(''.join(difflib.unified_diff(current.splitlines(True), contents[name].decode().splitlines(True),
              fromfile='project/' + name, tofile='upstream-template/' + name)), end='')


def plan(destination, contents, revision):
    manifest = destination / 'harness-upstream.json'
    initial = not manifest.exists()
    previous = json.loads(manifest.read_text()) if not initial else {'files': {}}
    # Check every write before making any changes. Legacy manifests may include
    # templates; release their ownership without comparing or overwriting them.
    for name in [*MANAGED, *TEMPLATES, 'harness-upstream.json']:
        path = destination / name
        if not path.resolve().is_relative_to(destination.resolve()):
            raise ValueError('Managed path escapes destination')
        if name in MANAGED and path.exists():
            current = hashlib.sha256(path.read_bytes()).hexdigest()
            if current != previous['files'].get(name):
                raise ValueError('Local changes in managed file: ' + name)
    result = {name: contents[name] for name in MANAGED}
    if initial:
        result.update({name: contents[name] for name in TEMPLATES if not (destination / name).exists()})
    result['harness-upstream.json'] = (json.dumps({
        'repository': 'https://github.com/big91987/he_skeleton', 'revision': revision,
        'files': {n: hashlib.sha256(contents[n]).hexdigest() for n in MANAGED}
    }, indent=2) + '\n').encode()
    return {name: data for name, data in result.items()
            if not (destination / name).exists() or (destination / name).read_bytes() != data}


def sync(source, destination, revision, show_template_diff=False):
    if source.resolve() == destination.resolve():
        raise ValueError('Source and product repositories must differ')
    if not (destination / '.git').exists():
        raise ValueError('Destination must already be a Git checkout')
    sha = subprocess.check_output(['git', 'rev-parse', '--verify', revision+'^{commit}'], cwd=source, text=True).strip()
    paths = {name: name for name in MANAGED} | TEMPLATES
    contents = {name: subprocess.check_output(['git', 'show', sha+':'+path], cwd=source)
                for name, path in paths.items()}
    if show_template_diff:
        template_diff(destination, contents)
        return []
    changes = plan(destination, contents, sha)
    for name, data in changes.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    print('Synced Harness revision', sha, '; existing project workflows and forms preserved.')
    return list(changes)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('destination', type=Path)
    p.add_argument('--ref', default='HEAD')
    p.add_argument('--template-diff', action='store_true', help='Only print template differences; write nothing')
    a = p.parse_args()
    sync(Path(__file__).resolve().parents[1], a.destination, a.ref, a.template_diff)
