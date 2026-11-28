#!/usr/bin/env python3
"""Check a candidate tree with the policy loaded from protected main.

Security entrypoints are content-pinned. A change to one of them requires a
separate, reviewed policy update on main before the changed entrypoint can pass.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

MAX_SCRIPT_BYTES = 2 * 1024 * 1024
PINNED_ENTRYPOINTS = {
    "scripts/publish_guard.sh": "a02307353e0664f1e690c4a0ac8bf03b98f2d5b45e97ea350a513d817c7459e0",
    "scripts/publish_rendered_subject.sh": "30678d18e248f8109aaa57fa94fd1e04bd2fe964e6e1595cc8132079580c3591",
    "scripts/publish_verified_subject.py": "6a409758d3d99f793ed99b7ce0e150e8b6fb5d17809aa170e6d3932361d8cfbb",
    "scripts/bootstrap_python.sh": "76f6b6974916d30233782c801fed538dc51cc81153a0468aa68e0511ac09fac2",
}
PUBLISH_PATTERNS = (
    r"\b(?:cp|rsync|mv|scp)\s+[^\n]*(?:views/rendered|rendered\.md|\$SRC_PATH)",
    r"\b(?:shutil\.copy|copyfile|copy2)\s*\([^\n]*(?:views/rendered|rendered\.md)",
    r"/Users/Shared/nuum-work/stage/[^\n]*\.rendered\.md",
)


def read_script(repo: Path, path: Path) -> bytes:
    if path.is_symlink() or not path.resolve(strict=True).is_relative_to(repo):
        raise ValueError(f"script is a symlink or escapes repository: {path}")
    if not path.is_file() or path.stat().st_size > MAX_SCRIPT_BYTES:
        raise ValueError(f"script is not a bounded regular file: {path}")
    raw = path.read_bytes()
    if len(raw) > MAX_SCRIPT_BYTES:
        raise ValueError(f"script exceeds size limit: {path}")
    return raw


def check(repo: Path) -> list[str]:
    repo = repo.resolve(strict=True)
    bad = []
    for relative, expected in PINNED_ENTRYPOINTS.items():
        try:
            actual = hashlib.sha256(read_script(repo, repo / relative)).hexdigest()
        except (OSError, ValueError) as exc:
            bad.append(f"{relative}: {exc}")
            continue
        if actual != expected:
            bad.append(f"{relative}: differs from the reviewed publish entrypoint")

    for path in sorted((repo / "scripts").rglob("*")):
        if not path.is_file() and not path.is_symlink():
            continue
        relative = path.relative_to(repo).as_posix()
        if relative in PINNED_ENTRYPOINTS or relative == "scripts/check_publish_guard_usage.py":
            continue
        try:
            content = read_script(repo, path).decode("utf-8", errors="replace")
        except (OSError, ValueError) as exc:
            bad.append(f"{relative}: {exc}")
            continue
        if any(re.search(pattern, content) for pattern in PUBLISH_PATTERNS):
            bad.append(f"{relative}: unreviewed rendered publication path")
    return bad


def main() -> None:
    repo = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    try:
        bad = check(repo)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"publish guard check rejected: {exc}") from exc
    if bad:
        raise SystemExit("publish guard check rejected:\n" + "\n".join(bad))
    print("publish guard usage check passed")


if __name__ == "__main__":
    main()
