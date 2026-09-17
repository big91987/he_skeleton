#!/usr/bin/env python3
"""Download latest Harness, validate it, and install it on an isolated product test branch."""
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
    parser.add_argument("--branch", required=True, help="Target codex/harness-test-* branch; created from product default branch")
    parser.add_argument("--run", action="store_true", help="Dispatch the test branch after synchronization")
    parser.add_argument("--task", type=int, help="Existing product Issue number")
    parser.add_argument("--instruction", default="clarify 检查需求并提出必要问题")
    args = parser.parse_args()
    if not args.branch.startswith("codex/harness-test-") or subprocess.run(
            ["git", "check-ref-format", "--branch", args.branch], capture_output=True).returncode:
        raise ValueError("Use a valid codex/harness-test-* branch")
    if args.run and (not args.task or args.task <= 0):
        raise ValueError("--run requires a positive --task")
    if args.repository == UPSTREAM:
        raise ValueError("Target must be a separate product repository")
    revision = api(f"repos/{UPSTREAM}/commits/{urllib.parse.quote(args.ref, safe='')}")["sha"]
    info = api(f"repos/{args.repository}")
    base = info["default_branch"]
    branches = api(f"repos/{args.repository}/git/matching-refs/heads/{args.branch}")
    existing_branch = next((b for b in branches if b["ref"] == "refs/heads/" + args.branch), None)
    head = existing_branch["object"]["sha"] if existing_branch else api(
        f"repos/{args.repository}/git/ref/heads/{base}")["object"]["sha"]
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
        if changes:
            tree = api(f"repos/{args.repository}/git/trees", "POST", {
                "base_tree": api(f"repos/{args.repository}/git/commits/{head}")["tree"]["sha"],
                "tree": [{"path": name, "mode": "100644", "type": "blob", "content": content}
                         for name, content in changes.items()]})
            commit = api(f"repos/{args.repository}/git/commits", "POST", {
                "message": "Test Harness " + revision[:12], "tree": tree["sha"], "parents": [head]})
            if existing_branch:
                api(f"repos/{args.repository}/git/refs/heads/{args.branch}", "PATCH",
                    {"sha": commit["sha"], "force": False})
            else:
                api(f"repos/{args.repository}/git/refs", "POST",
                    {"ref": "refs/heads/" + args.branch, "sha": commit["sha"]})
        elif not existing_branch:
            api(f"repos/{args.repository}/git/refs", "POST",
                {"ref": "refs/heads/" + args.branch, "sha": head})
        print("Test branch: https://github.com/" + args.repository + "/tree/" + args.branch)
        if args.run:
            api(f"repos/{args.repository}/actions/workflows/harness.yml/dispatches", "POST",
                {"ref": args.branch, "inputs": {"task": str(args.task), "instruction": args.instruction}}, raw=True)
            print("Dispatched test branch; follow its Actions run. No main update or upgrade PR.")


if __name__ == "__main__":
    main()
