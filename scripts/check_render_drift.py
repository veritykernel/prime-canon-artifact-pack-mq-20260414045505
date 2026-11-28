#!/usr/bin/env python3
"""Read-only verification of frozen render receipts against current inputs."""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

import yaml

from render_binding import compute_view_hash
from render_receipts import active_receipt_paths
from secure_projection_path import read_rendered
from validate_pack import load_yaml as load_bounded_yaml


def load_yaml(path: Path) -> dict:
    if path.is_symlink():
        raise ValueError(f"render input is a symlink: {path}")
    return load_bounded_yaml(path)


def current_output_hash(repo: Path, subject_slug: str) -> str | None:
    try:
        raw = read_rendered(repo, subject_slug)
    except FileNotFoundError:
        return None
    return hashlib.sha256(raw).hexdigest()


def inspect(repo: Path, subject_slug: str) -> tuple[str, str]:
    repo = repo.resolve(strict=True)
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", subject_slug):
        raise ValueError("invalid subject slug")
    view = load_yaml(repo / "views" / "current" / f"{subject_slug}.yaml")
    execution_path, drift_path = active_receipt_paths(repo, subject_slug, view)
    execution = load_yaml(execution_path)
    drift = load_yaml(drift_path)
    view_spec, execution_spec, drift_spec = view["spec"], execution["spec"], drift["spec"]
    expected_ref = f"views/rendered/{subject_slug}.md"
    output_sha = current_output_hash(repo, subject_slug)
    current_view_hash = compute_view_hash(repo, subject_slug, view)

    if output_sha is None:
        status = "missing_output"
    elif output_sha != execution_spec.get("output_sha256"):
        status = "out_of_sync"
    elif (current_view_hash != view_spec.get("view_hash")
          or current_view_hash != drift_spec.get("current_view_hash")
          or output_sha != drift_spec.get("output_sha256")
          or execution_spec.get("output_ref") != expected_ref
          or drift_spec.get("output_ref") != expected_ref
          or execution_spec.get("target_view_ref") != view_spec.get("view_id")
          or drift_spec.get("target_view_ref") != view_spec.get("view_id")
          or drift_spec.get("plan_ref") != execution_spec.get("plan_ref")
          or drift_spec.get("drift_status") != "in_sync"
          or drift_spec.get("blocker") is not False
          or drift_spec.get("recommended_route") != "export_prep"):
        status = "stale_view"
    else:
        status = "in_sync"
    return drift["metadata"]["object_id"], status


def main() -> None:
    repo = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    subject_slug = sys.argv[2] if len(sys.argv) > 2 else "subject-0001"
    try:
        receipt_id, status = inspect(repo, subject_slug)
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as exc:
        raise SystemExit(f"render drift check rejected: {exc}") from exc
    blocker = status != "in_sync"
    route = "export_prep" if not blocker else "render_refresh"
    print(receipt_id)
    print(f"drift_status={status}")
    print(f"blocker={str(blocker).lower()}")
    print(f"recommended_route={route}")
    if blocker:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
