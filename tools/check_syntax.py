#!/usr/bin/env python3
"""CLI utility to run syntax checks on the server package."""
from __future__ import annotations

import compileall
import sys
from pathlib import Path


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent
    target_dir = project_root / "server"

    if not target_dir.exists():
        print(f"Target directory '{target_dir}' does not exist.", file=sys.stderr)
        return 1

    success = compileall.compile_dir(str(target_dir), quiet=1)

    if not success:
        print("Syntax error detected while compiling Python files in 'server'.", file=sys.stderr)
        return 1

    print("Python syntax check passed for 'server'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
