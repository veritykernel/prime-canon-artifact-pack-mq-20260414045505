#!/usr/bin/env python3
"""Check a PR checkout with code from the protected base checkout only.

Enforcement surfaces are byte-identical to base. A deliberate change to these
surfaces needs a separately reviewed policy successor and ruleset transition.
"""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

from check_publish_guard_usage import check

FROZEN_PATHS = (
    ".github/CODEOWNERS",
    ".github/workflows/publish-guard-check.yml",
    ".github/workflows/publish-guard-trusted.yml",
    ".github/workflows/validate-prime-canon.yml",
    "scripts/check_immutable_history.py",
    "scripts/check_publish_guard_trusted.py",
    "scripts/check_publish_guard_usage.py",
    "scripts/check_export_prep.py",
    "scripts/check_render_drift.py",
    "scripts/render_binding.py",
    "scripts/render_text.py",
    "scripts/render_receipts.py",
    "scripts/secure_projection_path.py",
    "scripts/promotion_preflight.py",
    "scripts/immutable_receipt.py",
    "scripts/validate_pack.py",
    "scripts/schema_contract.py",
    "scripts/enroll_source_units.py",
    "scripts/extract_candidate_claims.py",
    "scripts/bootstrap_subject.sh",
    "scripts/bootstrap_python.sh",
    "scripts/build_evidence_and_admissibility.py",
    "scripts/build_promotion_readiness.py",
    "scripts/build_rendered_projection.py",
    "scripts/scout_contradictions_and_supersession.py",
    "scripts/freeze_render_plan_family_cycle2.py",
    "scripts/promote_nodes_and_current_state.py",
    "scripts/prove_merge_queue.sh",
    "scripts/select_proof_run.py",
    "scripts/publish_guard.sh",
    "scripts/publish_guard_commit.sh",
    "scripts/publish_rendered_subject.sh",
    "scripts/publish_rendered_subject_commit.sh",
    "scripts/publish_verified_subject.py",
    "control/render/render-profile.default.yaml",
    "control/render/render-order.default.yaml",
    "control/render/render-targets.default.yaml",
    "control/render/render-redaction.default.yaml",
    "control/publish/publish-targets.default.yaml",
    "schemas/prime-canon-bundle.schema.json",
    "requirements.txt",
)
MAX_FROZEN_BYTES = 1024 * 1024
SHADOW_MODULES = set(getattr(sys, "stdlib_module_names", ())) | {
    "yaml", "jsonschema", "attrs", "attr", "referencing", "rpds",
    "jsonschema_specifications",
}


def bounded_regular_bytes(root: Path, relative: str) -> bytes:
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute() or any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"unsafe path {relative}")
    directory_fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        for part in parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                              | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        fd = os.open(parts[-1], os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                     | os.O_NONBLOCK, dir_fd=directory_fd)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FROZEN_BYTES:
                raise ValueError(f"unsafe enforcement file {relative}")
            raw = stream.read(MAX_FROZEN_BYTES + 1)
        if len(raw) > MAX_FROZEN_BYTES:
            raise ValueError(f"oversized enforcement file {relative}")
        return raw
    finally:
        os.close(directory_fd)


def check_candidate(base: Path, candidate: Path) -> list[str]:
    issues = []
    scripts = candidate / "scripts"
    if scripts.is_symlink() or not scripts.is_dir():
        issues.append("candidate has no safe scripts directory")
    else:
        for path in scripts.iterdir():
            module = path.name.split(".", 1)[0]
            if module in SHADOW_MODULES and not (base / "scripts" / path.name).exists():
                issues.append(f"scripts/{path.name}: new module shadows a trusted dependency")
    for relative in FROZEN_PATHS:
        try:
            if bounded_regular_bytes(base, relative) != bounded_regular_bytes(candidate, relative):
                issues.append(f"{relative}: differs from protected base")
        except (OSError, ValueError) as exc:
            issues.append(f"{relative}: {exc}")
    for family in ("receipts/immutable", "canon/nodes", "canon/source_units"):
        base_dir, candidate_dir = base / family, candidate / family
        if not base_dir.is_dir() or base_dir.is_symlink():
            issues.append(f"protected base has no safe {family} directory")
            continue
        if not candidate_dir.is_dir() or candidate_dir.is_symlink():
            issues.append(f"candidate has no safe {family} directory")
            continue
        for path in sorted(base_dir.rglob("*")):
            if path.is_dir() and not path.is_symlink():
                continue
            relative = path.relative_to(base).as_posix()
            try:
                if bounded_regular_bytes(base, relative) != bounded_regular_bytes(candidate, relative):
                    issues.append(f"{relative}: prior reviewed object changed")
            except (OSError, ValueError) as exc:
                issues.append(f"{relative}: prior reviewed object unsafe or missing: {exc}")
        for path in sorted(candidate_dir.rglob("*")):
            if path.is_dir() and not path.is_symlink():
                continue
            relative = path.relative_to(candidate).as_posix()
            try:
                bounded_regular_bytes(candidate, relative)
            except (OSError, ValueError) as exc:
                issues.append(f"{relative}: candidate reviewed object unsafe: {exc}")
    if not issues:
        issues.extend(check(candidate))
    return issues


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: check_publish_guard_trusted.py BASE_CHECKOUT CANDIDATE_CHECKOUT")
    base, candidate = map(lambda arg: Path(arg).resolve(strict=True), sys.argv[1:])
    if base == candidate:
        raise SystemExit("base and candidate must be distinct checkouts")
    issues = check_candidate(base, candidate)
    if issues:
        print("trusted publish guard failed:", file=sys.stderr)
        for issue in issues:
            print(issue, file=sys.stderr)
        raise SystemExit(1)
    print("trusted publish guard passed")


if __name__ == "__main__":
    main()
