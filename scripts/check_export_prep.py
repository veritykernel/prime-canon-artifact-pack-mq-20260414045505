#!/usr/bin/env python3
"""Authorize export prep only after fresh, read-only render verification."""

from __future__ import annotations

import sys
from pathlib import Path

from check_render_drift import inspect


def main() -> None:
    repo = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    subject_slug = sys.argv[2] if len(sys.argv) > 2 else "subject-0001"
    try:
        _, status = inspect(repo, subject_slug)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SystemExit(f"export prep rejected: {exc}") from exc
    ready = status == "in_sync"
    print(f"drift_status={status}")
    print(f"blocker={'false' if ready else 'true'}")
    print(f"recommended_route={'export_prep' if ready else 'render_refresh'}")
    print(f"export_prep_ready={'true' if ready else 'false'}")
    if not ready:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
