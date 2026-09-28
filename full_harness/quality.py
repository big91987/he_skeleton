"""Python quality gate for product files; runtime code has its own source CI."""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# Direct script execution also works from an imported product checkout.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from full_harness.common import CONTROL, files


def python_files(root):
    return sorted(
        name
        for name in files(root)
        if name.endswith(".py") and not name.startswith(CONTROL)
    )


def checks(root):
    if not python_files(root):
        return []
    return [
        {
            "name": "Python formatting and lint",
            "argv": [sys.executable, str(Path(__file__).resolve()), "check"],
            "stages": ["development", "verification"],
        }
    ]


def run(root, mode):
    names = python_files(root)
    if not names:
        print("No product Python files; Python quality checks are not applicable.")
        return 0
    executable = shutil.which("ruff")
    if executable is None:
        print(
            "Ruff is missing. Install the pinned development dependency before continuing.",
            file=sys.stderr,
        )
        return 125
    config = Path(__file__).with_name("ruff.toml")
    options = ["--no-cache", "--config", str(config)]
    commands = (
        [["check", "--fix"], ["format"], ["format", "--check"], ["check"]]
        if mode == "fix"
        else [["format", "--check"], ["check"]]
    )
    failed = False
    for command in commands:
        print("Python quality: " + " ".join(command), flush=True)
        result = subprocess.run(
            [executable, *command, *options, "--", *names], cwd=root, check=False
        )
        if mode == "check" or command in (["format", "--check"], ["check"]):
            failed |= result.returncode != 0
    return int(failed)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["fix", "check"])
    args = parser.parse_args()
    raise SystemExit(run(Path.cwd(), args.mode))
