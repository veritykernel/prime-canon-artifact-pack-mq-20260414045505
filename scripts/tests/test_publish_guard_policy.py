from __future__ import annotations

import shutil
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE / "scripts"))

from check_publish_guard_usage import PINNED_ENTRYPOINTS, check


class PublishGuardPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        (self.repo / "scripts").mkdir()
        for relative in PINNED_ENTRYPOINTS:
            target = self.repo / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE / relative, target)

    def test_current_entrypoints_pass(self) -> None:
        self.assertEqual(check(self.repo), [])

    def test_changed_publisher_fails_even_if_it_mentions_guard(self) -> None:
        publisher = self.repo / "scripts" / "publish_rendered_subject.sh"
        publisher.write_text(publisher.read_text() + "\n# publish_guard.sh\n")
        self.assertTrue(any("publish_rendered_subject.sh" in issue for issue in check(self.repo)))

    def test_new_direct_copy_fails_even_if_it_mentions_guard(self) -> None:
        path = self.repo / "scripts" / "rogue.sh"
        path.write_text("publish_guard.sh\n" + "cp " + "views/" + "rendered/x.md /tmp/x.md\n")
        self.assertTrue(any("rogue.sh" in issue for issue in check(self.repo)))

    def test_publisher_symlink_fails(self) -> None:
        publisher = self.repo / "scripts" / "publish_rendered_subject.sh"
        publisher.unlink()
        publisher.symlink_to(SOURCE / "scripts" / "publish_rendered_subject.sh")
        self.assertTrue(any("publish_rendered_subject.sh" in issue for issue in check(self.repo)))

    def test_candidate_venv_payload_is_never_run_by_guard(self) -> None:
        marker = self.repo / "candidate-venv-executed"
        venv = self.repo / ".venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "activate").write_text(f"touch {marker}\n")
        candidate_python = venv / "python3"
        candidate_python.write_text(f"#!/bin/sh\ntouch {marker}\nexit 0\n")
        candidate_python.chmod(0o755)
        guard = self.repo / "scripts" / "publish_guard.sh"
        for trusted in (str(candidate_python), "/usr/bin/python3"):
            result = subprocess.run(["bash", str(guard), "--", "/usr/bin/true"],
                                    cwd=self.repo, capture_output=True, text=True,
                                    env={**os.environ, "PRIME_CANON_TRUSTED_PYTHON": trusted})
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
