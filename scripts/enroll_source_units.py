#!/usr/bin/env python3
from __future__ import annotations

import csv
import fcntl
import hashlib
import io
import os
import re
import secrets
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml
from secure_projection_path import _open_directories

REQUIRED_COLUMNS = [
    "seq",
    "source_ref",
    "locator",
    "start",
    "end",
    "observed_at",
    "scope",
    "normalized_text",
]
MAX_TSV_BYTES = 2 * 1024 * 1024
MAX_ROWS = 256

def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def load_tsv(path: Path):
    if path.is_symlink():
        raise SystemExit(f"TSV path is a symlink: {path}")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_TSV_BYTES:
            raise SystemExit(f"TSV is not a bounded regular file: {path}")
        raw = stream.read(MAX_TSV_BYTES + 1)
    if len(raw) > MAX_TSV_BYTES:
        raise SystemExit(f"TSV exceeds {MAX_TSV_BYTES} bytes: {path}")
    with io.StringIO(raw.decode("utf-8"), newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        if reader.fieldnames is None:
            raise SystemExit(f"TSV has no header: {path}")
        if len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise SystemExit(f"TSV has duplicate columns: {path}")
        missing = [c for c in REQUIRED_COLUMNS if c not in reader.fieldnames]
        if missing:
            raise SystemExit(f"TSV missing required columns {missing}: {path}")
        rows = []
        for idx, row in enumerate(reader, start=2):
            if not any((row.get(k) or "").strip() for k in row.keys()):
                continue
            clean = {k: (v.strip() if isinstance(v, str) else "") for k, v in row.items()}
            for col in REQUIRED_COLUMNS:
                if not clean.get(col):
                    raise SystemExit(f"{path}:{idx}: missing required value for {col}")
            if len(rows) >= MAX_ROWS:
                raise SystemExit(f"TSV exceeds {MAX_ROWS} rows: {path}")
            rows.append(clean)
        if not rows:
            raise SystemExit(f"No source rows found in {path}")
        return rows

def sha256_text(parts):
    payload = "|".join(parts).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()

def _enroll_locked(repo: Path, subject_slug: str, tsv_path: Path) -> None:
    corpus_index_path = repo / "canon" / "corpora" / subject_slug / "index.yaml"
    if not corpus_index_path.exists() or corpus_index_path.is_symlink():
        raise SystemExit(f"Missing corpus index: {corpus_index_path}")
    rows = load_tsv(tsv_path)
    normalized_rows = []
    seen_sequences = set()
    for row in rows:
        raw_sequence = row["seq"]
        if not re.fullmatch(r"[0-9]{1,4}", raw_sequence) or not 1 <= int(raw_sequence) <= 9999:
            raise SystemExit(f"invalid source sequence: {raw_sequence}")
        sequence = f"{int(raw_sequence):04d}"
        if sequence in seen_sequences:
            raise SystemExit(f"duplicate normalized source sequence: {sequence}")
        seen_sequences.add(sequence)
        normalized_rows.append((row, sequence))

    corpus_directory_fd = _open_directories(repo, ("canon", "corpora", subject_slug))
    try:
        fd = os.open("index.yaml", os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | os.O_NONBLOCK,
                     dir_fd=corpus_directory_fd)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_TSV_BYTES:
                raise SystemExit("corpus index is not a bounded regular file")
            corpus = yaml.safe_load(stream.read(MAX_TSV_BYTES + 1))
    finally:
        os.close(corpus_directory_fd)

    corpus_id = corpus["spec"]["corpus_id"]
    now = utc_now()
    created_by = os.environ.get("SOURCE_UNIT_CREATED_BY", "human:operator")
    owners = [x for x in os.environ.get("SOURCE_UNIT_OWNERS", "team:prime-canon").split(",") if x]
    tags = [x for x in os.environ.get("SOURCE_UNIT_TAGS", f"prime-canon,{subject_slug},source-unit").split(",") if x]

    source_unit_ids = list(corpus["attributes"]["lineage"].get("source_unit_refs", []))
    source_refs = list(corpus["attributes"]["lineage"].get("source_refs", []))

    target_dir = repo / "canon" / "source_units" / subject_slug
    if target_dir.is_symlink() or (target_dir.exists() and not target_dir.resolve().is_relative_to(repo)):
        raise SystemExit("source-unit directory escapes repository")
    for _, seq in normalized_rows:
        object_id = f"pc.source_unit.{subject_slug}.{seq}"
        output = target_dir / f"unit-{seq}.yaml"
        if object_id in source_unit_ids or output.exists() or output.is_symlink():
            raise SystemExit(f"source-unit identity already exists; reconcile before re-enrollment: {object_id}")
    staged = []

    for row, seq in normalized_rows:
        object_id = f"pc.source_unit.{subject_slug}.{seq}"
        rel_path = f"canon/source_units/{subject_slug}/unit-{seq}.yaml"
        source_unit_ids.append(object_id)
        if row["source_ref"] not in source_refs:
            source_refs.append(row["source_ref"])

        source_kind = row.get("source_kind", "") or "chat_message"
        burden_level = row.get("burden_level", "") or "medium"
        sufficiency_status = row.get("sufficiency_status", "") or "unscored"
        evidence_class = row.get("evidence_class", "") or "human_assertion"
        risk_tier = row.get("risk_tier", "") or "medium"
        semantic_density = float(row.get("semantic_density", "") or "0.80")
        novelty_state = row.get("novelty_state", "") or "unknown"
        drift_sensitivity = row.get("drift_sensitivity", "") or "medium"
        maintenance_burden = row.get("maintenance_burden", "") or "low"
        replay_stability = row.get("replay_stability", "") or "stable"
        maturity = row.get("maturity", "") or "working"

        normalized_text = row["normalized_text"]
        checksum = sha256_text([
            row["source_ref"],
            row["locator"],
            row["start"],
            row["end"],
            normalized_text,
        ])

        data = {
            "kind": "PRIME_CANON_SOURCE_UNIT_V1",
            "version": "v1",
            "metadata": {
                "object_id": object_id,
                "display_name": row.get("display_name", "") or f"{subject_slug} source unit {seq}",
                "created_at": now,
                "updated_at": now,
                "created_by": created_by,
                "owners": owners,
                "tags": tags,
            },
            "attributes": {
                "identity": {
                    "corpus_id": corpus_id,
                    "subject_slug": subject_slug,
                    "canonical_home": rel_path,
                },
                "lineage": {
                    "source_refs": [row["source_ref"]],
                    "source_unit_refs": [],
                    "reduction_path": ["intake"],
                    "derivation_receipt_refs": [],
                },
                "evidence": {
                    "burden_level": burden_level,
                    "sufficiency_status": sufficiency_status,
                    "evidence_class": evidence_class,
                    "evidence_ref_count": 1,
                    "replayability_class": "high",
                },
                "governance": {
                    "jurisdiction_ref": "pc.jurisdiction.human-reviewer",
                    "approval_level": "peer",
                    "actor_class": "human",
                    "risk_tier": risk_tier,
                    "promotion_tier": "draft",
                    "freeze_class": "reviewed",
                },
                "semantic": {
                    "domain": "prime-canon",
                    "scope": row["scope"],
                    "dependency_footprint": [],
                    "semantic_density": semantic_density,
                    "novelty_state": novelty_state,
                },
                "relational": {
                    "contradiction_refs": [],
                    "supersedes": [],
                    "superseded_by": [],
                    "depends_on": [],
                    "section_refs": [],
                    "cluster_refs": [],
                },
                "operational": {
                    "lane_ref": "intake",
                    "repo_home": rel_path,
                    "active_state": "active",
                    "mirror_permissions": "local_only",
                    "maintenance_burden": maintenance_burden,
                    "route_destination": "reduction",
                },
                "temporal": {
                    "status_since": now,
                    "replay_stability": replay_stability,
                    "drift_sensitivity": drift_sensitivity,
                    "maturity": maturity,
                    "observed_at": row["observed_at"],
                    "reduced_at": now,
                },
            },
            "spec": {
                "source_unit_id": object_id,
                "corpus_id": corpus_id,
                "source_ref": row["source_ref"],
                "span_ref": {
                    "locator": row["locator"],
                    "start": int(row["start"]),
                    "end": int(row["end"]),
                },
                "normalized_text": normalized_text,
                "extraction_method": row.get("extraction_method", "") or "message-span-normalize@1.0.0",
                "source_kind": source_kind,
                "checksum": checksum,
            },
        }

        staged.append((f"unit-{seq}.yaml", yaml.safe_dump(data, sort_keys=False)))

    corpus["metadata"]["updated_at"] = now
    corpus["attributes"]["lineage"]["source_refs"] = source_refs
    corpus["attributes"]["lineage"]["source_unit_refs"] = source_unit_ids
    corpus["attributes"]["evidence"]["evidence_ref_count"] = len(source_refs)
    corpus["attributes"]["temporal"]["reduced_at"] = now
    corpus["attributes"]["temporal"]["status_since"] = now
    corpus["spec"]["source_refs"] = source_refs
    corpus["spec"]["source_count"] = len(source_refs)
    corpus_payload = yaml.safe_dump(corpus, sort_keys=False)
    directory_fd = _open_directories(repo, ("canon", "source_units", subject_slug), create_last=True)
    created = []
    committed = False
    try:
        # All rows and identities have been validated before the first write.
        # Each provenance object is installed exclusively; a concurrent writer
        # can cause a failed batch but can never replace an existing object.
        for filename, payload in staged:
            fd = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                         0o644, dir_fd=directory_fd)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            created.append(filename)
        os.fsync(directory_fd)
        corpus_directory_fd = _open_directories(repo, ("canon", "corpora", subject_slug))
        temporary_name = f".index.{secrets.token_hex(12)}.tmp"
        try:
            fd = os.open(temporary_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                         0o644, dir_fd=corpus_directory_fd)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(corpus_payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, corpus_index_path.name,
                       src_dir_fd=corpus_directory_fd, dst_dir_fd=corpus_directory_fd)
            committed = True
        finally:
            try:
                os.unlink(temporary_name, dir_fd=corpus_directory_fd)
            except FileNotFoundError:
                pass
            os.close(corpus_directory_fd)
    except BaseException:
        if not committed:
            for filename in created:
                os.unlink(filename, dir_fd=directory_fd)
        raise
    finally:
        os.close(directory_fd)


def main() -> None:
    repo = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(".").resolve()
    subject_slug = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("SUBJECT_SLUG", "subject-0001")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", subject_slug):
        raise SystemExit("invalid subject slug")
    tsv_path = Path(sys.argv[3]).absolute() if len(sys.argv) > 3 else repo / "work_orders" / subject_slug / "source-units.tsv"
    corpus_directory_fd = _open_directories(repo, ("canon", "corpora", subject_slug))
    try:
        lock_fd = os.open(".enroll.lock", os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                          0o600, dir_fd=corpus_directory_fd)
        try:
            info = os.fstat(lock_fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or info.st_uid != os.geteuid() or info.st_mode & 0o077 or info.st_size):
                raise SystemExit("unsafe source enrollment lock file")
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            _enroll_locked(repo, subject_slug, tsv_path)
        finally:
            os.close(lock_fd)
    finally:
        os.close(corpus_directory_fd)

if __name__ == "__main__":
    main()
