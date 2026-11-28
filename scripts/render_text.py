"""Deterministically derive the Markdown body from governed render inputs."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from render_binding import POLICY_PATHS, object_index, safe_bytes


def compose_rendered_text(subject: str, corpus_id: str, view_id: str,
                          generated_at: str, nodes: list[dict], policies: dict[str, dict],
                          generation: str) -> str:
    profile = policies[POLICY_PATHS[0]]
    order = policies[POLICY_PATHS[1]]
    targets = policies[POLICY_PATHS[2]]
    redaction = policies[POLICY_PATHS[3]]
    flag = profile["target_projection_flag"]
    output_format = profile["default_output_format"]
    if (flag != "rendered_text" or flag not in targets["allowed_projection_flags"]
            or flag not in targets["default_projection_flags"]
            or output_format != "markdown" or output_format not in targets["allowed_output_formats"]
            or order["ordering_mode"] != "active_node_refs"
            or redaction["policy_mode"] != "none"
            or profile["section_strategy"] != "linear_nodes"
            or profile["ordering_strategy"] != "active_node_order"
            or profile["heading_style"] not in ("title_only", "numbered")
            or profile["include_receipt_footer"] not in (True, False)):
        raise ValueError("render policy is outside the deterministic Markdown contract")
    if not nodes or not re.fullmatch(r"[a-z][a-z0-9-]{0,31}", generation):
        raise ValueError("invalid render nodes or generation")
    if not isinstance(generated_at, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", generated_at):
        raise ValueError("invalid render generation time")
    lines = [f"# {subject} rendered canon", ""]
    metadata = {"corpus_id": corpus_id, "current_state_view": view_id,
                "generated_at": generated_at}
    fields = profile.get("include_metadata_fields", [])
    if not isinstance(fields, list):
        raise ValueError("invalid render metadata fields")
    for field in fields:
        if field in metadata:
            lines.append(f"- {field}: `{metadata[field]}`")
    lines.extend((f"- active_node_count: `{len(nodes)}`", "", "## Promoted canon nodes", ""))
    for index, node in enumerate(nodes, start=1):
        body = node["spec"]["canonical_body"]
        if not isinstance(body, str):
            raise ValueError("canon node has no text body")
        lines.append(f"{index}. {body}" if profile["heading_style"] == "numbered" else f"- {body}")
    if profile["include_receipt_footer"]:
        lines.extend(("", "## Projection receipts", "",
                      f"- render_profile_ref: `{profile['profile_id']}`",
                      f"- render_plan_ref: `pc.render_plan.{subject}.{generation}`"))
    return "\n".join(lines) + "\n"


def expected_rendered_bytes(repo: Path, subject: str, view: dict, generation: str) -> bytes:
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", subject):
        raise ValueError("invalid render subject")
    spec = view["spec"]
    corpus_id = f"pc.corpus.{subject}"
    if spec["scope_ref"] != corpus_id or spec["view_id"] != f"pc.current_state_view.{subject}.v1":
        raise ValueError("render view identity does not match subject")
    policies = {path: yaml.safe_load(safe_bytes(repo, path)) for path in POLICY_PATHS}
    snapshot = object_index(repo)
    nodes = []
    for node_id in spec["active_node_refs"]:
        match = re.fullmatch(rf"pc\.canon_node\.{re.escape(subject)}\.(\d{{4}})", node_id)
        if not match or node_id not in snapshot:
            raise ValueError(f"invalid active render node: {node_id}")
        relative, _, node = snapshot[node_id]
        if relative != f"canon/nodes/{subject}/node-{match.group(1)}.yaml":
            raise ValueError(f"render node path mismatch: {node_id}")
        nodes.append(node)
    return compose_rendered_text(subject, corpus_id, spec["view_id"], spec["generated_at"],
                                 nodes, policies, generation).encode("utf-8")
