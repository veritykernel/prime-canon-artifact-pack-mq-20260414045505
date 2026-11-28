"""Resolve the newest paired render receipts named by the current view."""

from __future__ import annotations

import re
from pathlib import Path


def active_receipt_paths(repo: Path, subject_slug: str, view: dict) -> tuple[Path, Path]:
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", subject_slug):
        raise ValueError("invalid subject slug")
    refs = view["spec"].get("derivation_receipt_refs", [])
    if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs) or len(refs) != len(set(refs)):
        raise ValueError("invalid or duplicate derivation receipt refs")
    execution_prefix = f"pc.render_execution_receipt.{subject_slug}."
    drift_prefix = f"pc.render_drift_receipt.{subject_slug}."
    executions = [(idx, ref[len(execution_prefix):]) for idx, ref in enumerate(refs)
                  if isinstance(ref, str) and ref.startswith(execution_prefix)]
    drifts = [(idx, ref[len(drift_prefix):]) for idx, ref in enumerate(refs)
              if isinstance(ref, str) and ref.startswith(drift_prefix)]
    if not executions or not drifts:
        raise ValueError("current view has no paired render receipts")
    execution_idx, execution_generation = executions[-1]
    drift_idx, drift_generation = drifts[-1]
    if (execution_generation != drift_generation or execution_idx >= drift_idx
            or not re.fullmatch(r"[a-z][a-z0-9-]{0,31}", execution_generation)):
        raise ValueError("current view render receipts do not form one generation")
    suffix = "" if execution_generation == "default" else f"-{execution_generation}"
    receipt_dir = repo / "receipts" / "immutable" / subject_slug
    return receipt_dir / f"render-execution{suffix}.yaml", receipt_dir / f"render-drift{suffix}.yaml"
