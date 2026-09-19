#!/usr/bin/env python3
"""Install a pinned Harness into one existing GitHub product repository (macOS ARM64)."""
import argparse
import hashlib
import json
import platform
from pathlib import Path
import shutil
import subprocess
import urllib.request

from sync_project import sync


def run(args, cwd=None, capture=False):
    return subprocess.run(args,cwd=cwd,check=True,text=True,
                          stdout=subprocess.PIPE if capture else None,timeout=300).stdout


def api(method, path, data=None):
    args=['gh','api','--method',method,path]
    if data is not None:args+=['--input','-']
    p=subprocess.run(args,input=json.dumps(data) if data is not None else None,
                     text=True,capture_output=True,check=True,timeout=60)
    return json.loads(p.stdout) if p.stdout.strip() else None


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('repository',help='owner/product-repository; already created on GitHub')
    p.add_argument('--directory',required=True,type=Path)
    p.add_argument('--ref',default='HEAD',help='committed scaffold revision')
    p.add_argument('--activate',action='store_true',help='publish managed files, configure Pages and start local Runner')
    a=p.parse_args()
    if platform.system()!='Darwin' or platform.machine()!='arm64':
        raise SystemExit('This bootstrap currently supports macOS ARM64 only')
    for tool in ['gh','git','node','npm','codex']:
        if not shutil.which(tool):raise SystemExit('Missing prerequisite: '+tool)
    info=api('GET','repos/'+a.repository)
    if not info.get('permissions',{}).get('admin'):
        raise SystemExit('Repository admin access required')
    if info['private']:
        raise SystemExit('This first static-preview bootstrap requires a public demo project for Pages')
    checkout=a.directory.expanduser().resolve()
    source=Path(__file__).resolve().parents[1]
    if not checkout.exists():run(['gh','repo','clone',a.repository,str(checkout)])
    origin=run(['git','remote','get-url','origin'],checkout,True).strip()
    expected='https://github.com/'+a.repository+'.git'
    if origin.rstrip('/') not in {expected,expected[:-4],'git@github.com:'+a.repository+'.git'}:
        raise SystemExit('Checkout origin does not match requested product repository')
    if run(['git','status','--porcelain'],checkout,True).strip():
        raise SystemExit('Commit or preserve local work before bootstrap')
    branch=run(['git','symbolic-ref','--short','HEAD'],checkout,True).strip()
    if info['default_branch']!='main' or branch!='main':
        raise SystemExit('Initial bootstrap currently requires the main branch checkout')
    changed_files=sync(source,checkout,a.ref)
    if not a.activate:
        print('Prepared files only. Review diff, then rerun on a clean checkout with --activate to deploy.')
        return
    # Stage only changed tool files and newly installed templates.
    manifest=json.loads((checkout/'harness-upstream.json').read_text())
    if changed_files:
        run(['git','add',*changed_files],checkout)
    changed=subprocess.run(['git','diff','--cached','--quiet'],cwd=checkout).returncode
    if changed==1:run(['git','commit','-m','Update pinned Harness infrastructure'],checkout)
    elif changed!=0:raise SystemExit('Cannot inspect staged diff')
    run(['git','push','origin','HEAD'],checkout)
    labels=api('GET','repos/'+a.repository+'/labels?per_page=100')
    if not any(x['name']=='harness' for x in labels):
        api('POST','repos/'+a.repository+'/labels',{'name':'harness','color':'2563EB'})
    try:api('GET','repos/'+a.repository+'/pages')
    except subprocess.CalledProcessError as error:
        if '404' not in error.stderr:raise
        api('POST','repos/'+a.repository+'/pages',{'build_type':'workflow'})
    root=checkout.with_name(checkout.name+'_runner')
    for name in ['runtime','sessions','previews','tools']:(root/name).mkdir(parents=True,exist_ok=True)
    root.chmod(0o700)
    runtime=root/'runtime'
    if not (runtime/'config.sh').exists():
        release=api('GET','repos/actions/runner/releases/latest')
        asset=next(x for x in release['assets'] if x['name'].startswith('actions-runner-osx-arm64-'))
        digest=asset.get('digest','')
        if not digest.startswith('sha256:'):raise SystemExit('Official Runner release lacks SHA256 digest')
        archive=root/'runner.tar.gz'
        with urllib.request.urlopen(asset['browser_download_url'],timeout=60) as response, archive.open('wb') as out:
            shutil.copyfileobj(response,out)
        if hashlib.sha256(archive.read_bytes()).hexdigest()!=digest[7:]:
            raise SystemExit('Runner checksum mismatch')
        run(['tar','-xzf',str(archive),'-C',str(runtime)])
    run(['npm','install','--prefix',str(root/'tools'),'--save-exact','playwright@1.58.2'])
    run([str(root/'tools/node_modules/.bin/playwright'),'install','chromium'])
    registration=runtime/'.runner'
    if registration.exists():
        saved=json.loads(registration.read_text())
        if saved.get('gitHubUrl','').rstrip('/')!='https://github.com/'+a.repository:
            raise SystemExit('Runner belongs to another repository; refusing to reuse credentials')
    else:
        token=api('POST','repos/'+a.repository+'/actions/runners/registration-token')['token']
        run(['./config.sh','--unattended','--url','https://github.com/'+a.repository,
             '--token',token,'--name',checkout.name+'-local','--labels','he-skeleton',
             '--work',str(root/'jobs')],runtime)
    if not (runtime/'.service').exists():run(['./svc.sh','install'],runtime)
    run(['./svc.sh','start'],runtime)
    run(['./svc.sh','status'],runtime)
    print('Product repository:',info['html_url'])
    print('Harness revision:',manifest['revision'])
    print('Ready for an owner-created task; this is provisioning, not an end-to-end acceptance result.')


if __name__=='__main__':
    try:main()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        # Registration command arguments contain a short-lived token; never print them.
        status = 'timeout' if isinstance(error, subprocess.TimeoutExpired) else 'exit '+str(error.returncode)
        raise SystemExit('External setup command failed ('+status+'). Provisioning is incomplete.') from None
