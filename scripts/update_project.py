#!/usr/bin/env python3
"""Download latest Harness, validate it, and propose a managed-files-only product upgrade."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import urllib.parse

UPSTREAM = "big91987/he_skeleton"
MANAGED = ["harness/agent.py", "harness/loop.py", "harness/browser.cjs",
           ".github/workflows/harness.yml", ".github/ISSUE_TEMPLATE/task.yml"]


def api(path, method="GET", body=None, raw=False):
    args = ["gh", "api", "--method", method, path]
    if body is not None:
        args += ["--input", "-"]
    result = subprocess.run(args, input=json.dumps(body).encode() if body is not None else None,
                            capture_output=True, check=True, timeout=120)
    return result.stdout if raw else json.loads(result.stdout)


def snapshot(repository, revision, destination):
    data = api(f"repos/{repository}/tarball/{revision}", raw=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for entry in archive.getmembers():
            parts = Path(entry.name).parts[1:]
            if not parts:
                continue
            target = destination.joinpath(*parts)
            if not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError("Archive path escapes snapshot")
            if entry.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif entry.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.extractfile(entry).read())
            else:
                raise ValueError("Snapshot contains unsupported link or special file")


def prepare(source, product, revision):
    manifest = product / "harness-upstream.json"
    previous = json.loads(manifest.read_text()) if manifest.exists() else {"files": {}}
    contents = {name: (source / name).read_bytes() for name in MANAGED}
    for name in MANAGED:
        path = product / name
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() != previous["files"].get(name):
            raise ValueError("Product modified managed file: " + name)
    result = {name: data.decode() for name, data in contents.items()}
    result["harness-upstream.json"] = json.dumps({
        "repository": "https://github.com/" + UPSTREAM, "revision": revision,
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}
    }, indent=2) + "\n"
    return {name: data for name, data in result.items()
            if not (product / name).exists() or (product / name).read_text() != data}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", help="owner/product repository")
    parser.add_argument("--ref", default="main", help="Upstream branch/tag/SHA; default main")
    parser.add_argument("--publish-pr", action="store_true", help="Publish an upgrade branch and PR after validation")
    args = parser.parse_args()
    if args.repository == UPSTREAM:
        raise ValueError("Target must be a separate product repository")
    revision = api(f"repos/{UPSTREAM}/commits/{urllib.parse.quote(args.ref, safe='')}")["sha"]
    info = api(f"repos/{args.repository}")
    base = info["default_branch"]
    head = api(f"repos/{args.repository}/git/ref/heads/{base}")["object"]["sha"]
    with tempfile.TemporaryDirectory(prefix="harness-update-") as folder:
        root = Path(folder)
        source, product = root / "source", root / "product"
        source.mkdir(); product.mkdir()
        snapshot(UPSTREAM, revision, source)
        snapshot(args.repository, head, product)
        # Existing upstream tests use committed revisions, so reconstruct the downloaded snapshot locally.
        for command in (["git", "init", "-q"], ["git", "add", "."],
                        ["git", "-c", "user.name=Harness", "-c", "user.email=harness@example.invalid",
                         "-c", "core.hooksPath=/dev/null", "commit", "-qm", "Downloaded upstream snapshot"]):
            subprocess.run(command, cwd=source, check=True, capture_output=True)
        subprocess.run(["python3", "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=source, check=True)
        changes = prepare(source, product, revision)
        for name, content in changes.items():
            path = product / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        for name in ("harness/agent.py", "harness/loop.py"):
            compile((product / name).read_text(), name, "exec")
        subprocess.run(["node", "--check", str(product / "harness/browser.cjs")], check=True)
        print("Validated upstream:", revision, "Product base:", head, flush=True)
        print("Changed managed files:", ", ".join(changes) or "none", flush=True)
        if not changes or not args.publish_pr:
            return
        branch = "codex/harness-update-" + revision[:12] + "-" + head[:8]
        existing = api(f"repos/{args.repository}/pulls?state=open&head=" + urllib.parse.quote(info['owner']['login'] + ':' + branch))
        if existing:
            print(existing[0]["html_url"])
            return
        # Base is pinned; never write the default branch or force-update a product task branch.
        tree = api(f"repos/{args.repository}/git/trees", "POST", {
            "base_tree": api(f"repos/{args.repository}/git/commits/{head}")["tree"]["sha"],
            "tree": [{"path": name, "mode": "100644", "type": "blob", "content": content}
                     for name, content in changes.items()]})
        commit = api(f"repos/{args.repository}/git/commits", "POST", {
            "message": "Update Harness to " + revision[:12], "tree": tree["sha"], "parents": [head]})
        api(f"repos/{args.repository}/git/refs", "POST", {"ref": "refs/heads/" + branch, "sha": commit["sha"]})
        pr = api(f"repos/{args.repository}/pulls", "POST", {
            "title": "Update Harness to " + revision[:12], "head": branch, "base": base,
            "body": "Sync managed infrastructure from " + UPSTREAM + "@" + revision +
            ". Business files are preserved. Upstream unit tests and copied Python/JavaScript syntax checks passed. "
            "After merge, use `/harness publish` on an existing verified task to check preview delivery, "
            "or `/harness <feedback>` for a new execution round. Live workflow validation is still pending."})
        print(pr["html_url"])


if __name__ == "__main__":
    main()
