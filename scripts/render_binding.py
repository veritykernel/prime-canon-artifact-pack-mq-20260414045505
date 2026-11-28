"""Bind a render view to the exact referenced canon and governance bytes."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path

import yaml

from secure_projection_path import _open_directories
from validate_pack import check_tree_bound

POLICY_PATHS = (
    "control/render/render-profile.default.yaml",
    "control/render/render-order.default.yaml",
    "control/render/render-targets.default.yaml",
    "control/render/render-redaction.default.yaml",
)
REFERENCE_FIELDS = (
    "active_node_refs",
    "active_edge_refs",
    "active_contradiction_refs",
    "unresolved_blocker_refs",
    "derivation_receipt_refs",
)
MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_OBJECTS = 5000
MAX_TOTAL_BYTES = 64 * 1024 * 1024


def safe_bytes(repo: Path, relative: str) -> bytes:
    """Read a bounded regular repo file without following any path component."""
    path = Path(relative)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise ValueError(f"unsafe render input path: {relative}")
    directory_fd = _open_directories(repo, path.parts[:-1])
    try:
        fd = os.open(path.name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | os.O_NONBLOCK,
                     dir_fd=directory_fd)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_INPUT_BYTES:
                raise ValueError(f"render input is not a bounded regular file: {relative}")
            raw = stream.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise ValueError(f"render input exceeds size limit: {relative}")
        return raw
    finally:
        os.close(directory_fd)


def object_index(repo: Path) -> dict[str, tuple[str, bytes, dict]]:
    """Resolve object IDs to one verified canonical path and byte snapshot."""
    objects: dict[str, tuple[str, bytes, dict]] = {}
    total_bytes = 0
    for root_name in ("canon", "receipts", "replay", "control"):
        root = repo / root_name
        if root.is_symlink() or not root.is_dir():
            raise ValueError(f"missing or linked render object root: {root_name}")
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise ValueError(f"linked render object path: {path.relative_to(repo)}")
            if not path.name.endswith(".yaml"):
                continue
            if len(objects) >= MAX_OBJECTS:
                raise ValueError("render object count exceeds bound")
            relative = path.relative_to(repo).as_posix()
            raw = safe_bytes(repo, relative)
            total_bytes += len(raw)
            if total_bytes > MAX_TOTAL_BYTES:
                raise ValueError("render object bytes exceed aggregate bound")
            obj = yaml.safe_load(raw)
            check_tree_bound(obj)
            if not isinstance(obj, dict) or "kind" not in obj:
                continue
            metadata = obj.get("metadata", {})
            identity = obj.get("attributes", {}).get("identity", {})
            object_id = metadata.get("object_id")
            if not isinstance(object_id, str) or not object_id:
                raise ValueError(f"missing render object identity: {relative}")
            if identity.get("canonical_home") != relative:
                raise ValueError(f"render object canonical path mismatch: {relative}")
            if object_id in objects:
                raise ValueError(f"duplicate render object identity: {object_id}")
            objects[object_id] = (relative, raw, obj)
    return objects


def _active_render_pair(subject: str, refs: list[str]) -> set[str]:
    execution_prefix = f"pc.render_execution_receipt.{subject}."
    drift_prefix = f"pc.render_drift_receipt.{subject}."
    executions = [(i, ref) for i, ref in enumerate(refs) if ref.startswith(execution_prefix)]
    drifts = [(i, ref) for i, ref in enumerate(refs) if ref.startswith(drift_prefix)]
    if not executions and not drifts:
        return set()
    if not executions or not drifts:
        raise ValueError("render receipt references are not paired")
    execution_index, execution = executions[-1]
    drift_index, drift = drifts[-1]
    if (execution_index >= drift_index
            or execution[len(execution_prefix):] != drift[len(drift_prefix):]):
        raise ValueError("active render receipt generation mismatch")
    # These two receipts contain the view hash, so their bytes cannot be inputs
    # to that same hash. Their exact IDs remain bound by the view spec; drift and
    # publication separately verify their byte-level output and view bindings.
    return {execution, drift}


def compute_view_hash(
    repo: Path, subject_slug: str, view: dict,
    *, snapshot: dict[str, tuple[str, bytes, dict]] | None = None,
    policy_bytes: dict[str, bytes] | None = None,
) -> str:
    repo = repo.resolve(strict=True)
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", subject_slug):
        raise ValueError("invalid render subject slug")
    spec = dict(view["spec"])
    spec.pop("view_hash", None)
    references: dict[str, list[str]] = {}
    for field in REFERENCE_FIELDS:
        refs = spec.get(field, [])
        if (not isinstance(refs, list) or any(not isinstance(ref, str) or not ref for ref in refs)
                or len(refs) != len(set(refs))):
            raise ValueError(f"invalid or duplicate {field}")
        references[field] = refs
    ignored = _active_render_pair(subject_slug, references["derivation_receipt_refs"])
    objects = snapshot if snapshot is not None else object_index(repo)
    inputs = []
    for field, refs in references.items():
        for ref in refs:
            if ref in ignored:
                continue
            if ref not in objects:
                raise ValueError(f"unresolved render reference: {ref}")
            relative, raw, obj = objects[ref]
            identity = obj["attributes"]["identity"]
            if (identity.get("subject_slug") != subject_slug
                    or identity.get("corpus_id") != f"pc.corpus.{subject_slug}"):
                raise ValueError(f"cross-subject render reference: {ref}")
            if field == "active_node_refs":
                match = re.fullmatch(rf"pc\.canon_node\.{re.escape(subject_slug)}\.(\d{{4}})", ref)
                if not match or relative != f"canon/nodes/{subject_slug}/node-{match.group(1)}.yaml":
                    raise ValueError(f"invalid active node path or ID: {ref}")
            elif field == "active_edge_refs" and not relative.startswith(f"canon/supersession/{subject_slug}/"):
                raise ValueError(f"invalid active edge path: {ref}")
            elif field == "active_contradiction_refs" and not relative.startswith(f"canon/contradictions/{subject_slug}/"):
                raise ValueError(f"invalid active contradiction path: {ref}")
            inputs.append({"field": field, "ref": ref, "path": relative,
                           "sha256": hashlib.sha256(raw).hexdigest()})
    for relative in POLICY_PATHS:
        raw = policy_bytes[relative] if policy_bytes is not None else safe_bytes(repo, relative)
        inputs.append({"field": "render_policy", "path": relative,
                       "sha256": hashlib.sha256(raw).hexdigest()})
    payload = {"binding_version": 3, "domain": "prime-canon-render-view-v3",
               "view_spec": spec, "inputs": inputs}
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
