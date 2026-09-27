#!/usr/bin/env python3
"""Install the light conversation template and shared runtime from a pinned revision."""

import argparse
from pathlib import Path

from install_full import install

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--ref", default="HEAD")
    args = parser.parse_args()
    install(Path(__file__).resolve().parents[1], args.destination, args.ref, "light")
