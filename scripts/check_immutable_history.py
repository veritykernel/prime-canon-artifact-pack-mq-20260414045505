#!/usr/bin/env python3
"""Reject updates or removals of reviewed objects already present at the PR base."""

from __future__ import annotations

import copy
import re
import subprocess
import sys
from pathlib import Path

import yaml

from check_render_drift import inspect
from render_binding import safe_bytes
from render_receipts import active_receipt_paths
from validate_pack import check_tree_bound

MAX_VIEW_BYTES = 2 * 1024 * 1024


def changed_immutable_paths(base: str, head: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=DMRTUX", "--find-renames",
         base, head, "--", "receipts/immutable/", "canon/nodes/", "canon/source_units/"],
        check=True, capture_output=True, text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def _git_bytes(revision: str, path: str) -> bytes:
    result = subprocess.run(["git", "show", f"{revision}:{path}"],
                            check=True, capture_output=True)
    if len(result.stdout) > MAX_VIEW_BYTES:
        raise ValueError(f"prior view exceeds byte limit: {path}")
    return result.stdout


def _base_has(revision: str, path: str) -> bool:
    return subprocess.run(["git", "cat-file", "-e", f"{revision}:{path}"],
                          capture_output=True, check=False).returncode == 0


def _governed_view_shape(view: dict) -> dict:
    shaped = copy.deepcopy(view)
    shaped["metadata"].pop("updated_at", None)
    shaped["attributes"]["temporal"].pop("reduced_at", None)
    shaped["attributes"]["temporal"].pop("status_since", None)
    shaped["attributes"]["operational"].pop("route_destination", None)
    for key in ("derivation_receipt_refs", "rendered_projection_refs",
                "generated_at", "view_hash"):
        shaped["spec"].pop(key, None)
    return shaped


def changed_view_issues(base: str, head: str, repo: Path) -> list[str]:
    result = subprocess.run(["git", "diff", "--name-status", "--find-renames",
                             base, head, "--", "views/current/"],
                            check=True, capture_output=True, text=True)
    issues = []
    for line in result.stdout.splitlines():
        fields = line.split("\t")
        status, relative = fields[0], fields[-1]
        if status == "A":
            # CI cannot attest that a candidate ran the external signed
            # promotion path. Keep new governed views held until a trusted
            # signer-bound admission check exists on protected main.
            issues.append(f"{relative}: new current view requires trusted signed-promotion admission")
            continue
        if status != "M":
            issues.append(f"{relative}: existing current view was deleted, renamed or type-changed")
            continue
        subject = Path(relative).stem
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", subject):
            issues.append(f"{relative}: invalid subject path")
            continue
        try:
            before = yaml.safe_load(_git_bytes(base, relative))
            after = yaml.safe_load(safe_bytes(repo, relative))
            check_tree_bound(before)
            check_tree_bound(after)
            if not isinstance(before, dict) or not isinstance(after, dict):
                raise ValueError("current view is not an object")
            if _governed_view_shape(before) != _governed_view_shape(after):
                raise ValueError("reviewed current view changed outside a render-only successor")
            old_refs = before["spec"]["derivation_receipt_refs"]
            new_refs = after["spec"]["derivation_receipt_refs"]
            if (not isinstance(old_refs, list) or not isinstance(new_refs, list)
                    or new_refs[:len(old_refs)] != old_refs
                    or len(new_refs) != len(old_refs) + 2):
                raise ValueError("render successor must append exactly one receipt pair")
            execution_path, drift_path = active_receipt_paths(repo, subject, after)
            if (new_refs[-2] != f"pc.render_execution_receipt.{subject}.{new_refs[-2].rsplit('.', 1)[-1]}"
                    or new_refs[-1] != f"pc.render_drift_receipt.{subject}.{new_refs[-2].rsplit('.', 1)[-1]}"):
                raise ValueError("render successor receipt IDs do not form the exact pair")
            for path in (execution_path, drift_path):
                if _base_has(base, path.relative_to(repo).as_posix()):
                    raise ValueError(f"render successor reuses an existing receipt: {path}")
            if after["attributes"]["operational"]["route_destination"] != "export-prep":
                raise ValueError("render successor has an unexpected route")
            if after["spec"]["rendered_projection_refs"] != [f"views/rendered/{subject}.md"]:
                raise ValueError("render successor has an unexpected output path")
            if inspect(repo, subject)[1] != "in_sync":
                raise ValueError("render successor does not verify against current inputs")
        except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError,
                subprocess.CalledProcessError) as exc:
            issues.append(f"{relative}: {exc}")
    return issues


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: check_immutable_history.py BASE_SHA HEAD_SHA", file=sys.stderr)
        return 2
    base, head = sys.argv[1:]
    try:
        paths = changed_immutable_paths(base, head)
        paths.extend(changed_view_issues(base, head, Path.cwd().resolve()))
    except (subprocess.CalledProcessError, OSError, ValueError) as exc:
        detail = exc.stderr.strip() if isinstance(exc, subprocess.CalledProcessError) and isinstance(exc.stderr, str) else str(exc)
        print(f"immutable history check failed: {detail}", file=sys.stderr)
        return 2
    if paths:
        print("Immutable history or governed current-view transition failed:", file=sys.stderr)
        for path in paths:
            print(f"  {path}", file=sys.stderr)
        return 1
    print("Immutable history and current-view transition passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
