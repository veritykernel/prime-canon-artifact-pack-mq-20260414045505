#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from datetime import datetime
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator


MAX_OBJECT_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_OBJECTS = 5000
MAX_ERRORS = 50
MAX_TREE_NODES = 100000
MAX_TREE_DEPTH = 64


def check_tree_bound(data: object) -> None:
    """Bound traversal after YAML alias expansion, including repeated references."""
    stack = [(data, 0)]
    count = 0
    while stack:
        value, depth = stack.pop()
        count += 1
        if count > MAX_TREE_NODES or depth > MAX_TREE_DEPTH:
            raise ValueError("YAML object exceeds tree size or depth limit")
        if isinstance(value, dict):
            stack.extend((child, depth + 1) for child in value.values())
        elif isinstance(value, list):
            stack.extend((child, depth + 1) for child in value)


ROOT_FAMILIES = {
    "PRIME_CANON_REPO_MANIFEST_V1": "control/repo.manifest.yaml",
    "PRIME_CANON_ATTRIBUTE_DICTIONARY_V1": "control/attributes/",
    "PRIME_CANON_FORMULA_PROFILE_V1": "control/formulas/",
    "PRIME_CANON_ADMISSIBILITY_PROFILE_V1": "control/admissibility/",
    "PRIME_CANON_JURISDICTION_BINDING_V1": "control/jurisdictions/",
    "PRIME_CANON_LANE_MANIFEST_V1": "control/lanes/",
    "PRIME_CANON_CORPUS_INDEX_V1": "canon/corpora/",
    "PRIME_CANON_SOURCE_UNIT_V1": "canon/source_units/",
    "PRIME_CANON_CANDIDATE_CLAIM_V1": "canon/candidate_claims/",
    "PRIME_CANON_EVIDENCE_LINK_V1": "canon/evidence_links/",
    "PRIME_CANON_ADMISSIBILITY_DECISION_V1": "receipts/immutable/",
    "PRIME_CANON_FORMULA_EVAL_RECEIPT_V1": "receipts/immutable/",
    "PRIME_CANON_CONTRADICTION_BUNDLE_V1": "canon/contradictions/",
    "PRIME_CANON_REDUCTION_DECISION_RECEIPT_V1": "receipts/immutable/",
    "PRIME_CANON_SUPERSESSION_EDGE_V1": "canon/supersession/",
    "PRIME_CANON_NODE_V1": "canon/nodes/",
    "PRIME_CANON_PROMOTION_READINESS_PACKET_V1": "receipts/immutable/",
    "PRIME_CANON_REPLAY_MANIFEST_V1": "replay/manifests/",
    "PRIME_CANON_CURRENT_STATE_VIEW_V1": "views/current/",
}


def iso_ok(ts: str) -> bool:
    try:
        datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return True
    except Exception:
        return False


def load_yaml(path: Path):
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_OBJECT_BYTES:
            raise ValueError("not a bounded regular YAML file")
        raw = stream.read(MAX_OBJECT_BYTES + 1)
    if len(raw) > MAX_OBJECT_BYTES:
        raise ValueError("YAML file exceeds size limit")
    data = yaml.safe_load(raw)
    check_tree_bound(data)
    return data


def build_validators(schema_bundle: dict[str, object]):
    defs = schema_bundle["$defs"]
    return {
        kind: Draft202012Validator(defs[kind])
        for kind in defs.keys()
    }


def iter_object_files(repo_root: Path):
    for base in ["control", "canon", "receipts", "replay", "views"]:
        start = repo_root / base
        if not start.exists():
            continue
        for path in start.rglob("*.yaml"):
            yield path


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate prime canon artifact pack.")
    parser.add_argument("repo_root", nargs="?", default=".", help="Path to repo root.")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    schema_path = repo_root / "schemas" / "prime-canon-bundle.schema.json"
    if not schema_path.exists():
        print(f"ERROR: missing schema bundle: {schema_path}", file=sys.stderr)
        return 2

    if schema_path.stat().st_size > MAX_OBJECT_BYTES:
        print("ERROR: schema bundle exceeds size limit", file=sys.stderr)
        return 2
    bundle = json.loads(schema_path.read_text(encoding="utf-8"))
    validators = build_validators(bundle)

    errors = []
    warnings = []
    checked = 0
    total_bytes = 0

    for path in iter_object_files(repo_root):
        rel = path.relative_to(repo_root).as_posix()
        checked += 1
        if checked > MAX_OBJECTS:
            errors.append(f"object count exceeds {MAX_OBJECTS}")
            break
        try:
            total_bytes += path.lstat().st_size
            if total_bytes > MAX_TOTAL_BYTES:
                raise ValueError(f"aggregate YAML input exceeds {MAX_TOTAL_BYTES} bytes")
            data = load_yaml(path)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            errors.append(f"{rel}: {exc}")
            if len(errors) >= MAX_ERRORS:
                break
            continue

        if not isinstance(data, dict) or "kind" not in data:
            continue

        kind = data["kind"]

        if not isinstance(kind, str) or kind not in validators:
            errors.append(f"{rel}: unknown kind {str(kind)[:200]}")
            continue

        validator = validators[kind]
        for err in validator.iter_errors(data):
            loc = ".".join(str(x) for x in err.absolute_path) or "<root>"
            errors.append(f"{rel}: schema error at {loc[:200]}: {err.message[:400]}")
            if len(errors) >= MAX_ERRORS:
                break
        if len(errors) >= MAX_ERRORS:
            break

        expected = ROOT_FAMILIES.get(kind)
        if expected:
            if expected.endswith(".yaml"):
                if rel != expected:
                    errors.append(f"{rel}: expected exact path {expected} for {kind}")
            else:
                if not rel.startswith(expected):
                    errors.append(f"{rel}: expected path prefix {expected} for {kind}")

        try:
            canonical_home = data["attributes"]["identity"]["canonical_home"]
            if canonical_home != rel:
                errors.append(f"{rel}: canonical_home mismatch ({str(canonical_home)[:200]})")
        except Exception:
            errors.append(f"{rel}: missing attributes.identity.canonical_home")

        for label in ["created_at", "updated_at"]:
            ts = data.get("metadata", {}).get(label)
            if ts and not iso_ok(ts):
                errors.append(f"{rel}: metadata.{label} is not RFC3339-compatible")

        for label in ["observed_at", "reduced_at", "status_since"]:
            ts = data.get("attributes", {}).get("temporal", {}).get(label)
            if ts and not iso_ok(ts):
                errors.append(f"{rel}: attributes.temporal.{label} is not RFC3339-compatible")

        lane_ref = data.get("attributes", {}).get("operational", {}).get("lane_ref")
        if lane_ref == "promotion" and kind in {
            "PRIME_CANON_CANDIDATE_CLAIM_V1",
            "PRIME_CANON_SOURCE_UNIT_V1",
        }:
            if len(warnings) < MAX_ERRORS:
                warnings.append(f"{rel}: promotion lane usually should not hold raw candidates or source units")

        if rel.startswith("receipts/immutable/") and not kind.endswith(("DECISION_V1", "RECEIPT_V1", "PACKET_V1")):
            if len(warnings) < MAX_ERRORS:
                warnings.append(f"{rel}: immutable receipts directory usually stores receipt/decision/packet kinds only")

    print(f"Validated {checked} object files.")
    if warnings:
        print("\nWarnings:")
        for w in warnings:
            print(f"  - {w}")

    if errors:
        print("\nErrors:")
        for e in errors:
            print(f"  - {e}")
        if len(errors) >= MAX_ERRORS:
            print(f"  - stopped after {MAX_ERRORS} errors")
        return 1

    print("All prime canon objects passed schema and path validation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
