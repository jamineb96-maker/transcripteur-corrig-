#!/usr/bin/env python3
"""Fail if tab modules have duplicated static directories."""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    client_dir = REPO_ROOT / "client"
    canonical_root = client_dir / "tabs"
    duplicate_root = client_dir / "static" / "tabs"
    duplicates: list[str] = []
    target_tabs = ['documents_aide']
    if canonical_root.exists() and duplicate_root.exists():
        for name in target_tabs:
            if (canonical_root / name).is_dir() and (duplicate_root / name).is_dir():
                duplicates.append(name)
    if duplicates:
        print("Duplicate tab directories detected:")
        for name in duplicates:
            print(f" - {name}")
        return 1
    print("No duplicated tab directories detected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
