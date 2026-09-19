#!/usr/bin/env python3
"""Copy a committed Harness revision to a product repository without touching its application."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

MANAGED = ['harness/agent.py', 'harness/project.py', 'harness/loop.py', 'harness/browser.cjs', 'harness/delivery.py',
           '.github/workflows/harness.yml', '.github/ISSUE_TEMPLATE/task.yml']


def sync(source, destination, revision):
    if source.resolve() == destination.resolve():
        raise ValueError('Source and product repositories must differ')
    if not (destination / '.git').exists():
        raise ValueError('Destination must already be a Git checkout')
    sha = subprocess.check_output(['git','rev-parse','--verify',revision+'^{commit}'],cwd=source,text=True).strip()
    contents = {name:subprocess.check_output(['git','show',sha+':'+name],cwd=source) for name in MANAGED}
    manifest = destination/'harness-upstream.json'
    previous = json.loads(manifest.read_text()) if manifest.exists() else {'files':{}}
    for name in MANAGED:
        path = destination/name
        if not path.resolve().is_relative_to(destination.resolve()):
            raise ValueError('Managed path escapes destination')
        if path.exists():
            old_hash = previous['files'].get(name)
            current_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            if old_hash is None or current_hash != old_hash:
                raise ValueError('Local changes in managed file: '+name)
    for name, data in contents.items():
        path = destination/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(data)
    manifest.write_text(json.dumps({'repository':'https://github.com/big91987/he_skeleton',
        'revision':sha,'files':{n:hashlib.sha256(b).hexdigest() for n,b in contents.items()}},indent=2)+'\n')
    print('Synced Harness revision',sha,'to product checkout; app/ untouched.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('destination',type=Path)
    p.add_argument('--ref',default='HEAD')
    a=p.parse_args()
    sync(Path(__file__).resolve().parents[1],a.destination,a.ref)
