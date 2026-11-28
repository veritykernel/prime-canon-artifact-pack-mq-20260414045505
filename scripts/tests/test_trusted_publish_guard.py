from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_publish_guard_trusted import check_candidate

SOURCE = Path(__file__).resolve().parents[2]


class TrustedPublishGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.base, self.candidate = root / "base", root / "candidate"
        for checkout in (self.base, self.candidate):
            checkout.mkdir()
            for directory in ("scripts", ".github", "receipts/immutable",
                              "canon/nodes", "canon/source_units", "control"):
                shutil.copytree(SOURCE / directory, checkout / directory,
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            shutil.copyfile(SOURCE / "requirements.txt", checkout / "requirements.txt")

    def test_identical_reviewed_tree_passes(self):
        self.assertEqual(check_candidate(self.base, self.candidate), [])

    def test_old_receipt_remains_protected_if_candidate_disables_history_job(self):
        receipt = self.candidate / "receipts/immutable/subject-0001/render-drift.yaml"
        receipt.write_text(receipt.read_text() + "\n# changed\n")
        workflow = self.candidate / ".github/workflows/validate-prime-canon.yml"
        workflow.write_text(workflow.read_text().replace("python scripts/check_immutable_history.py", "true #"))
        issues = check_candidate(self.base, self.candidate)
        self.assertTrue(any("prior reviewed object changed" in issue and "render-drift" in issue for issue in issues))
        self.assertTrue(any("validate-prime-canon.yml" in issue for issue in issues))

    def test_symlinked_candidate_enforcement_file_is_rejected(self):
        workflow = self.candidate / ".github/workflows/publish-guard-check.yml"
        workflow.unlink()
        workflow.symlink_to(self.base / ".github/workflows/publish-guard-check.yml")
        self.assertTrue(any("publish-guard-check.yml" in issue for issue in
                            check_candidate(self.base, self.candidate)))

    def test_candidate_bootstrap_or_render_verifier_mutation_is_rejected(self):
        for name in ("bootstrap_python.sh", "render_text.py"):
            with self.subTest(name=name):
                path = self.candidate / "scripts" / name
                original = path.read_bytes()
                path.write_bytes(original + b"\n# candidate mutation\n")
                self.assertTrue(any(name in issue for issue in
                                    check_candidate(self.base, self.candidate)))
                path.write_bytes(original)

    def test_candidate_render_policy_mutation_is_rejected(self):
        policy = self.candidate / "control/render/render-profile.default.yaml"
        policy.write_text(policy.read_text() + "\n# candidate policy mutation\n")
        self.assertTrue(any("render-profile.default.yaml" in issue for issue in
                            check_candidate(self.base, self.candidate)))


if __name__ == "__main__":
    unittest.main()
