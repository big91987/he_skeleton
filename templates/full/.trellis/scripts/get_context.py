#!/usr/bin/env python3
"""Minimal spec discovery used by the bundled Trellis Skills; not the Trellis runtime."""
import argparse
import json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--mode',choices=['packages'],required=True);p.parse_args()
root=Path(__file__).resolve().parents[1]/'spec'
print(json.dumps({'spec_indexes':[x.relative_to(root.parent.parent).as_posix() for x in sorted(root.rglob('index.md'))]},indent=2))
