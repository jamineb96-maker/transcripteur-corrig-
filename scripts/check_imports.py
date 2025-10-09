#!/usr/bin/env python3
"""Validate that server tabs use absolute imports for shared packages."""

from __future__ import annotations

import re
import sys
from pathlib import Path

FORBIDDEN_PATTERNS = [
    re.compile(r"from\s+\.\.services"),
    re.compile(r"from\s+\.\.util"),
    re.compile(r"from\s+\.\.config"),
    re.compile(r"from\s+\.\.blueprints"),
]


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    tabs_root = repo_root / "server" / "tabs"
    violations: list[tuple[Path, int, str]] = []

    for py_file in tabs_root.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_PATTERNS:
            for match in pattern.finditer(text):
                line_no = text.count("\n", 0, match.start()) + 1
                snippet = match.group(0).strip()
                violations.append((py_file.relative_to(repo_root), line_no, snippet))

    if violations:
        print("Forbidden relative imports detected:", file=sys.stderr)
        for path, line_no, snippet in violations:
            print(f"  {path}:{line_no}: {snippet}", file=sys.stderr)
        return 1

    print("All server/tabs imports are clean.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
