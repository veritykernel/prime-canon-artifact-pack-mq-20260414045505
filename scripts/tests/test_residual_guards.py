from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
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
        for directory in ("canon", "receipts", "views", "control", "schemas"):
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
        result = subprocess.run([sys.executable, str(SOURCE / "scripts" / "build_rendered_projection.py"),
                                 str(self.repo), SUBJECT, "v2"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(old.read_bytes(), original)
        self.assertTrue((old.parent / "render-execution-v2.yaml").exists())
        self.assertEqual(inspect(self.repo, SUBJECT)[1], "in_sync")
        stage = self.root / "stage"
        stage.mkdir()
        target = stage / f"{SUBJECT}.rendered.md"
        cfg_path = self.repo / "control" / "publish" / "publish-targets.default.yaml"
        cfg = yaml.safe_load(cfg_path.read_text())
        cfg["subjects"][SUBJECT]["rendered_markdown_path"] = str(target)
        cfg_path.write_text(yaml.safe_dump(cfg))
        self.assertEqual(publish(self.repo, SUBJECT), target)
        self.assertEqual(target.read_bytes(), (self.repo / "views" / "rendered" / f"{SUBJECT}.md").read_bytes())

    def test_validator_rejects_oversized_yaml(self):
        path = self.repo / "oversized.yaml"
        path.write_bytes(b"a" * (MAX_OBJECT_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "bounded regular"):
            load_yaml(path)

    def test_history_gate_rejects_changed_receipt(self):
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=self.repo, check=True)
        receipt = self.repo / "receipts" / "immutable" / SUBJECT / "receipt.yaml"
        receipt.parent.mkdir(parents=True)
        receipt.write_text("original")
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=self.repo, check=True)
        base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True).strip()
        receipt.write_text("replaced")
        subprocess.run(["git", "commit", "-qam", "replace"], cwd=self.repo, check=True)
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True).strip()
        result = subprocess.run([sys.executable, str(SOURCE / "scripts" / "check_immutable_history.py"), base, head],
                                cwd=self.repo, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("receipt.yaml", result.stderr)

    def test_bootstrap_rejects_traversal_before_repo_write(self):
        outside = SOURCE.parent / "codex-bootstrap-traversal-probe"
        self.assertFalse(outside.exists())
        result = subprocess.run(["bash", str(SOURCE / "scripts" / "bootstrap_subject.sh"), "../codex-bootstrap-traversal-probe"],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SUBJECT_SLUG", result.stderr)
        self.assertFalse(outside.exists())


if __name__ == "__main__":
    unittest.main()
