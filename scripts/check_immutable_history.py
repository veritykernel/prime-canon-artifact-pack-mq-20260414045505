#!/usr/bin/env python3
"""Reject updates or removals of receipts already present at the PR base."""

from __future__ import annotations

import subprocess
import sys


def changed_immutable_paths(base: str, head: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=DMRTUX", "--find-renames",
         base, head, "--", "receipts/immutable/"],
        check=True, capture_output=True, text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: check_immutable_history.py BASE_SHA HEAD_SHA", file=sys.stderr)
        return 2
    base, head = sys.argv[1:]
    try:
        paths = changed_immutable_paths(base, head)
    except subprocess.CalledProcessError as exc:
        print(f"immutable history check failed: {exc.stderr.strip()}", file=sys.stderr)
        return 2
    if paths:
        print("Existing immutable receipts were changed or removed:", file=sys.stderr)
        for path in paths:
            print(f"  {path}", file=sys.stderr)
        return 1
    print("Existing immutable receipts are unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
