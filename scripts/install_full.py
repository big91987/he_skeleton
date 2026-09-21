#!/usr/bin/env python3
"""Install/upgrade the independent full workflow from a pinned toolbox commit."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def plan(destination,managed,templates,revision):
    destination=destination.resolve();manifest=destination/'.harness/full-upstream.json'
    previous=json.loads(manifest.read_text()) if manifest.exists() else None
    old=(previous or {}).get('files',{})
    def target(name):
        p=destination/name
        if not p.resolve().is_relative_to(destination):raise ValueError('Path escapes project: '+name)
        return p
    for name in set(managed)|set(old):
        p=target(name)
        if p.exists() and hashlib.sha256(p.read_bytes()).hexdigest()!=old.get(name):
            raise ValueError('Local edit in managed file: '+name)
    changes=dict(managed)
    if previous is None:
        changes.update({name:data for name,data in templates.items() if not target(name).exists()})
        for name in ['AGENTS.md','docs/README.md']:
            p=target(name)
            if p.exists():
                link='docs/harness-full.md' if name=='AGENTS.md' else 'harness-full.md'
                text=p.read_text()
                if '<!-- harness-full-index -->' not in text:
                    changes[name]=(text+'\n\n<!-- harness-full-index -->\nIndependent full workflow: ['+link+']('+link+'). Owner-managed document and stage paths: `.harness/full.json`.\n').encode()
    changes['.harness/full-upstream.json']=(json.dumps({'repository':'https://github.com/big91987/he_skeleton','revision':revision,
        'files':{n:hashlib.sha256(b).hexdigest() for n,b in managed.items()}},indent=2)+'\n').encode()
    for name in changes:target(name)
    for name in set(old)-set(managed):changes[name]=None
    return {n:b for n,b in changes.items() if b is None or not target(n).exists() or target(n).read_bytes()!=b}


def install(source,destination,ref):
    if source.resolve()==destination.resolve():raise ValueError('Install into a product checkout, not the toolbox')
    if not (destination/'.git').exists():raise ValueError('Destination must be a Git checkout')
    rev=subprocess.check_output(['git','rev-parse','--verify',ref+'^{commit}'],cwd=source,text=True).strip()
    names=subprocess.check_output(['git','ls-tree','-r','--name-only',rev,'--','full_harness','templates/full'],cwd=source,text=True).splitlines()
    managed={};templates={}
    for name in names:
        data=subprocess.check_output(['git','show',rev+':'+name],cwd=source)
        if name.startswith('full_harness/'):managed[name]=data
        else:templates[name[len('templates/full/'):]]=data
    if not managed or not templates:raise ValueError('Selected revision has no full workflow profile')
    changes=plan(destination,managed,templates,rev)
    for name,data in changes.items():
        p=destination/name
        if data is None:p.unlink(missing_ok=True)
        else:p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    print(json.dumps({'revision':rev,'changed':list(changes)},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('destination',type=Path);p.add_argument('--ref',default='HEAD');a=p.parse_args()
    install(Path(__file__).resolve().parents[1],a.destination,a.ref)
