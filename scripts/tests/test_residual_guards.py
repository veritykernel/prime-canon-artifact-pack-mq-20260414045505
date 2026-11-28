from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from immutable_receipt import write_new
from validate_pack import MAX_OBJECT_BYTES, load_yaml
from check_render_drift import inspect
from publish_verified_subject import publish
import yaml

SOURCE = Path(__file__).resolve().parents[2]
SUBJECT = "subject-0001"


class ResidualGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()

    def stage_pack(self):
        for directory in ("canon", "receipts", "replay", "views", "control", "schemas"):
            shutil.copytree(SOURCE / directory, self.repo / directory)

    def test_immutable_writer_preserves_existing_receipt(self):
        path = self.repo / "receipt.yaml"
        path.write_text("original")
        with self.assertRaisesRegex(SystemExit, "already exists"):
            write_new(self.repo, path, {"changed": True})
        self.assertEqual(path.read_text(), "original")

    def test_render_builder_refuses_existing_receipts_before_mutating_inputs(self):
        self.stage_pack()
        node = self.repo / "canon" / "nodes" / SUBJECT / "node-0001.yaml"
        view = self.repo / "views" / "current" / f"{SUBJECT}.yaml"
        original = (node.read_bytes(), view.read_bytes())
        result = subprocess.run([sys.executable, str(SOURCE / "scripts" / "build_rendered_projection.py"),
                                 str(self.repo), SUBJECT], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already exists", result.stderr)
        self.assertEqual((node.read_bytes(), view.read_bytes()), original)

    def test_topology_scout_refuses_existing_summary_before_mutating_corpus(self):
        self.stage_pack()
        corpus = self.repo / "canon" / "corpora" / SUBJECT / "index.yaml"
        original = corpus.read_bytes()
        result = subprocess.run([sys.executable, str(SOURCE / "scripts" / "scout_contradictions_and_supersession.py"),
                                 str(self.repo), SUBJECT], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already exists", result.stderr)
        self.assertEqual(corpus.read_bytes(), original)

    def test_topology_scout_writes_one_new_summary(self):
        self.stage_pack()
        summary = self.repo / "receipts" / "immutable" / SUBJECT / "topology-scout-summary.yaml"
        summary.unlink()
        result = subprocess.run([sys.executable, str(SOURCE / "scripts" / "scout_contradictions_and_supersession.py"),
                                 str(self.repo), SUBJECT], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(summary.exists())
        self.assertIn("topology-scout", summary.read_text())

    def test_successor_render_generation_preserves_old_receipts(self):
        self.stage_pack()
        old = self.repo / "receipts" / "immutable" / SUBJECT / "render-execution.yaml"
        original = old.read_bytes()
        node = self.repo / "canon" / "nodes" / SUBJECT / "node-0001.yaml"
        original_node = node.read_bytes()
        result = subprocess.run([sys.executable, str(SOURCE / "scripts" / "build_rendered_projection.py"),
                                 str(self.repo), SUBJECT, "v2"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(old.read_bytes(), original)
        self.assertEqual(node.read_bytes(), original_node)
        self.assertTrue((old.parent / "render-execution-v2.yaml").exists())
        self.assertEqual(inspect(self.repo, SUBJECT)[1], "in_sync")
        stage = self.root / "stage"
        stage.mkdir()
        stage = stage.resolve()
        target = stage / f"{SUBJECT}.rendered.md"
        cfg_path = self.repo / "control" / "publish" / "publish-targets.default.yaml"
        cfg = yaml.safe_load(cfg_path.read_text())
        cfg["subjects"][SUBJECT]["rendered_markdown_path"] = str(target)
        cfg_path.write_text(yaml.safe_dump(cfg))
        self.assertEqual(publish(self.repo, SUBJECT, approved_root=stage), target)
        self.assertEqual(target.read_bytes(), (self.repo / "views" / "rendered" / f"{SUBJECT}.md").read_bytes())

    def test_render_builder_rejects_rendered_symlink_without_touching_host_file(self):
        self.stage_pack()
        outside = self.root / "operator-file"
        outside.write_text("keep")
        rendered = self.repo / "views" / "rendered" / f"{SUBJECT}.md"
        rendered.unlink()
        rendered.symlink_to(outside)
        result = subprocess.run(
            [sys.executable, str(SOURCE / "scripts" / "build_rendered_projection.py"),
             str(self.repo), SUBJECT, "v2"],
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("output target is not a regular file", result.stderr)
        self.assertEqual(outside.read_text(), "keep")
        self.assertFalse((self.repo / "receipts" / "immutable" / SUBJECT / "render-execution-v2.yaml").exists())

    def test_fifo_render_input_fails_without_waiting_for_a_writer(self):
        self.stage_pack()
        rendered = self.repo / "views" / "rendered" / f"{SUBJECT}.md"
        rendered.unlink()
        os.mkfifo(rendered)
        result = subprocess.run(
            [sys.executable, str(SOURCE / "scripts" / "check_render_drift.py"),
             str(self.repo), SUBJECT],
            capture_output=True, text=True, timeout=3,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("bounded regular file", result.stderr)

    def test_validator_rejects_oversized_yaml(self):
        path = self.repo / "oversized.yaml"
        path.write_bytes(b"a" * (MAX_OBJECT_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "bounded regular"):
            load_yaml(path)

    def test_enrollment_does_not_replace_reviewed_source_units(self):
        self.stage_pack()
        unit = self.repo / "canon" / "source_units" / SUBJECT / "unit-0001.yaml"
        corpus = self.repo / "canon" / "corpora" / SUBJECT / "index.yaml"
        original = (unit.read_bytes(), corpus.read_bytes())
        result = subprocess.run(
            [sys.executable, str(SOURCE / "scripts" / "enroll_source_units.py"),
             str(self.repo), SUBJECT, str(SOURCE / "work_orders" / SUBJECT / "source-units.tsv")],
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already exists", result.stderr)
        self.assertEqual((unit.read_bytes(), corpus.read_bytes()), original)

    def test_new_source_unit_starts_unscored_and_preserves_prior_lineage(self):
        self.stage_pack()
        tsv = self.root / "new-source.tsv"
        tsv.write_text(
            "seq\tsource_ref\tlocator\tstart\tend\tobserved_at\tscope\tnormalized_text\n"
            "6\tchat://new-source\tline-1\t0\t4\t2026-04-13T00:00:00Z\tproof\ttest\n"
        )
        corpus = self.repo / "canon" / "corpora" / SUBJECT / "index.yaml"
        old_ids = yaml.safe_load(corpus.read_text())["attributes"]["lineage"]["source_unit_refs"]
        result = subprocess.run(
            [sys.executable, str(SOURCE / "scripts" / "enroll_source_units.py"),
             str(self.repo), SUBJECT, str(tsv)], capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        unit = yaml.safe_load((self.repo / "canon" / "source_units" / SUBJECT / "unit-0006.yaml").read_text())
        self.assertEqual(unit["attributes"]["evidence"]["sufficiency_status"], "unscored")
        self.assertEqual(unit["attributes"]["evidence"]["evidence_class"], "human_assertion")
        new_ids = yaml.safe_load(corpus.read_text())["attributes"]["lineage"]["source_unit_refs"]
        self.assertEqual(new_ids[:-1], old_ids)

    def test_history_gate_rejects_changed_receipt(self):
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=self.repo, check=True)
        receipt = self.repo / "receipts" / "immutable" / SUBJECT / "receipt.yaml"
        receipt.parent.mkdir(parents=True)
        receipt.write_text("original")
        node = self.repo / "canon" / "nodes" / SUBJECT / "node-0001.yaml"
        unit = self.repo / "canon" / "source_units" / SUBJECT / "unit-0001.yaml"
        node.parent.mkdir(parents=True)
        unit.parent.mkdir(parents=True)
        node.write_text("original")
        unit.write_text("original")
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=self.repo, check=True)
        base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True).strip()
        receipt.write_text("replaced")
        node.write_text("replaced")
        unit.write_text("replaced")
        subprocess.run(["git", "commit", "-qam", "replace"], cwd=self.repo, check=True)
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True).strip()
        result = subprocess.run([sys.executable, str(SOURCE / "scripts" / "check_immutable_history.py"), base, head],
                                cwd=self.repo, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("receipt.yaml", result.stderr)
        self.assertIn("node-0001.yaml", result.stderr)
        self.assertIn("unit-0001.yaml", result.stderr)

    def test_history_gate_rejects_structural_current_view_edit(self):
        self.stage_pack()
        for args in (["init", "-q"], ["config", "user.name", "Test"],
                     ["config", "user.email", "test@example.invalid"],
                     ["add", "."], ["commit", "-qm", "base"]):
            subprocess.run(["git", *args], cwd=self.repo, check=True)
        base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True).strip()
        path = self.repo / "views" / "current" / f"{SUBJECT}.yaml"
        view = yaml.safe_load(path.read_text())
        view["spec"]["active_node_refs"].pop()
        path.write_text(yaml.safe_dump(view))
        subprocess.run(["git", "commit", "-qam", "change view"], cwd=self.repo, check=True)
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True).strip()
        result = subprocess.run(
            [sys.executable, str(SOURCE / "scripts" / "check_immutable_history.py"), base, head],
            cwd=self.repo, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("outside a render-only successor", result.stderr)

    def test_history_gate_accepts_verified_render_successor_only(self):
        self.stage_pack()
        for args in (["init", "-q"], ["config", "user.name", "Test"],
                     ["config", "user.email", "test@example.invalid"],
                     ["add", "."], ["commit", "-qm", "base"]):
            subprocess.run(["git", *args], cwd=self.repo, check=True)
        base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True).strip()
        built = subprocess.run(
            [sys.executable, str(SOURCE / "scripts" / "build_rendered_projection.py"),
             str(self.repo), SUBJECT, "v2"], capture_output=True, text=True,
        )
        self.assertEqual(built.returncode, 0, built.stderr)
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-qm", "render successor"], cwd=self.repo, check=True)
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True).strip()
        result = subprocess.run(
            [sys.executable, str(SOURCE / "scripts" / "check_immutable_history.py"), base, head],
            cwd=self.repo, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_bootstrap_rejects_traversal_before_repo_write(self):
        outside = SOURCE.parent / "codex-bootstrap-traversal-probe"
        self.assertFalse(outside.exists())
        result = subprocess.run(["bash", str(SOURCE / "scripts" / "bootstrap_subject.sh"), "../codex-bootstrap-traversal-probe"],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SUBJECT_SLUG", result.stderr)
        self.assertFalse(outside.exists())

    def test_bootstrap_rejects_linked_index_and_render_leaves(self):
        for leaf in ("index", "render"):
            with self.subTest(leaf=leaf):
                bootstrap = self.root / f"bootstrap-{leaf}"
                shutil.copytree(SOURCE / "scripts", bootstrap / "scripts",
                                ignore=shutil.ignore_patterns("__pycache__"))
                shutil.copytree(SOURCE / "canon", bootstrap / "canon")
                (bootstrap / "views" / "rendered").mkdir(parents=True)
                venv_bin = bootstrap / ".venv" / "bin"
                venv_bin.mkdir(parents=True)
                (venv_bin / "python3").symlink_to(sys.executable)
                (venv_bin / "activate").write_text(
                    f'export PATH="{Path(sys.executable).parent}:$PATH"\n')
                sentinel = self.root / f"outside-{leaf}.txt"
                sentinel.write_text("KEEP")
                index = bootstrap / "canon" / "corpora" / "new-subject" / "index.yaml"
                rendered = bootstrap / "views" / "rendered" / "new-subject.md"
                target = index if leaf == "index" else rendered
                target.parent.mkdir(parents=True, exist_ok=True)
                target.symlink_to(sentinel)
                result = subprocess.run(
                    ["bash", str(bootstrap / "scripts" / "bootstrap_subject.sh"), "new-subject"],
                    capture_output=True, text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("bootstrap destination already exists", result.stderr)
                self.assertEqual(sentinel.read_text(), "KEEP")
                self.assertFalse((rendered if leaf == "index" else index).exists())
if __name__ == "__main__":
    unittest.main()
