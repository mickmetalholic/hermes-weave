"""End-to-end tests against a real local bare Git repository."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PACKAGE = Path(__file__).resolve().parents[1] / "src"


def git(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(["git", *( ["-C", str(cwd)] if cwd else [] ), *args], check=True, capture_output=True, text=True)


class WeaveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.remote = self.root / "data.git"
        git("init", "--bare", "--initial-branch=main", str(self.remote))
        seed = self.root / "seed"
        git("init", "--initial-branch=main", str(seed))
        (seed / "README.md").write_text("Private test data\n")
        git("add", "README.md", cwd=seed)
        git("-c", "user.email=test@example.test", "-c", "user.name=Test", "commit", "-m", "initial", cwd=seed)
        git("remote", "add", "origin", str(self.remote), cwd=seed)
        git("push", "-u", "origin", "main", cwd=seed)
        for host in ("a", "b"):
            home = self.root / host / ".hermes"
            (home / "skills").mkdir(parents=True)
            (home / "memories").mkdir()
            self.weave(host, "init", "--host", host, "--remote", str(self.remote),
                       "--hermes-home", str(home), "--worktree", str(self.root / host / "data"),
                       *( ["--share-memory"] if host == "a" else [] ))

    def weave(self, host: str, *args: str, ok: bool = True) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "PYTHONPATH": str(PACKAGE)}
        config = self.root / host / "config.json"
        proc = subprocess.run([sys.executable, "-S", "-m", "hermes_weave", "--config", str(config), *args],
                              capture_output=True, text=True, env=env)
        if ok and proc.returncode:
            self.fail(f"weave {host} {args} failed: {proc.stderr}\n{proc.stdout}")
        if not ok:
            self.assertNotEqual(proc.returncode, 0, f"Unexpected success: {args}")
        return proc

    def skill(self, host: str, name: str, content: str) -> Path:
        dest = self.root / host / ".hermes" / "skills" / name
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "SKILL.md").write_text(content)
        return dest

    def test_two_way_skill_exchange_preserves_provenance(self) -> None:
        self.skill("a", "review-code", "# From A\n")
        self.skill("b", "write-tests", "# From B\n")
        self.weave("a", "sync")
        self.weave("b", "sync")
        self.weave("a", "pull")
        remote_a = self.root / "a" / "data" / "hosts"
        self.assertTrue((remote_a / "a" / "skills" / "review-code" / "SKILL.md").exists())
        self.assertTrue((remote_a / "b" / "skills" / "write-tests" / "SKILL.md").exists())
        self.assertIn("new", self.weave("b", "review").stdout)
        self.weave("b", "apply", "a", "review-code")
        self.weave("b", "sync")
        self.assertFalse((self.root / "b" / "data" / "hosts" / "b" / "skills" / "review-code").exists(),
                         "Imported skill must never be republished as original")
        source = self.root / "a" / ".hermes" / "skills" / "review-code" / "SKILL.md"
        source.write_text("# Updated by A\n")
        self.weave("a", "sync")
        self.weave("b", "pull")
        review = json.loads(self.weave("b", "review", "--json").stdout)
        self.assertEqual(review["peers"][0]["skills"][0]["status"], "update")
        self.weave("b", "apply", "a", "review-code", ok=False)
        self.weave("b", "apply", "a", "review-code", "--replace")
        self.assertEqual((self.root / "b" / ".hermes" / "skills" / "review-code" / "SKILL.md").read_text(), "# Updated by A\n")
        self.assertEqual(len(list((self.root / "b" / ".hermes" / "skills").glob("review-code.weave-backup-*"))), 1)

    def test_memory_is_opt_in_and_never_applied(self) -> None:
        a = self.root / "a" / ".hermes" / "memories" / "MEMORY.md"
        b = self.root / "b" / ".hermes" / "memories" / "MEMORY.md"
        a.write_text("Prefer functional programming\n")
        b.write_text("Keep local settings\n")
        self.weave("a", "sync")
        self.weave("b", "sync")
        self.assertTrue((self.root / "b" / "data" / "hosts" / "a" / "memory" / "MEMORY.md").exists())
        self.assertFalse((self.root / "b" / "data" / "hosts" / "b" / "memory").exists())
        self.assertEqual(b.read_text(), "Keep local settings\n")

    def test_secret_and_symlink_skill_never_exported(self) -> None:
        bad = self.skill("a", "cloud", "# Cloud\n")
        (bad / ".env").write_text("API_KEY=should-never-leak")
        outside = self.root / "outside"
        outside.write_text("private")
        linked = self.skill("a", "linked", "# Linked\n")
        (linked / "data").symlink_to(outside)
        self.weave("a", "sync")
        self.assertFalse((self.root / "a" / "data" / "hosts" / "a" / "skills" / "cloud").exists())
        self.assertFalse((self.root / "a" / "data" / "hosts" / "a" / "skills" / "linked").exists())

    def test_collision_needs_explicit_rename(self) -> None:
        self.skill("a", "common", "# A\n")
        self.skill("b", "common", "# B\n")
        self.weave("a", "sync")
        self.weave("b", "pull")
        self.assertIn("conflict", self.weave("b", "review").stdout)
        self.weave("b", "apply", "a", "common", ok=False)
        self.weave("b", "apply", "a", "common", "--as", "common-from-a")
        self.assertEqual((self.root / "b" / ".hermes" / "skills" / "common" / "SKILL.md").read_text(), "# B\n")
        self.weave("b", "sync")
        self.assertFalse((self.root / "b" / "data" / "hosts" / "b" / "skills" / "common-from-a").exists())

    def test_promote_intentionally_forks_import(self) -> None:
        self.skill("a", "helper", "# A\n")
        self.weave("a", "sync")
        self.weave("b", "pull")
        self.weave("b", "apply", "a", "helper")
        self.weave("b", "promote", "helper")
        self.weave("b", "sync")
        self.assertTrue((self.root / "b" / "data" / "hosts" / "b" / "skills" / "helper" / "SKILL.md").exists())

    def test_nested_skill_and_renamed_frontmatter(self) -> None:
        self.skill("a", "devops/deploy", "---\nname: deploy\ndescription: ship\n---\n# Deploy\n")
        self.weave("a", "sync")
        self.weave("b", "pull")
        review = self.weave("b", "review").stdout
        self.assertIn("devops/deploy", review)
        self.weave("b", "apply", "a", "devops/deploy", "--as", "deploy-from-a")
        content = (self.root / "b" / ".hermes" / "skills" / "deploy-from-a" / "SKILL.md").read_text()
        self.assertIn("name: deploy-from-a", content)
        self.weave("b", "sync")
        self.assertFalse((self.root / "b" / "data" / "hosts" / "b" / "skills" / "deploy-from-a").exists())

    def test_repository_symlink_cannot_escape_on_import(self) -> None:
        # A malicious peer may commit a symlink in the data repo. Import must refuse it.
        target = self.skill("a", "test", "# Test\n")
        self.weave("a", "sync")
        self.weave("b", "pull")
        src = self.root / "b" / "data" / "hosts" / "a" / "skills" / "test"
        import shutil
        shutil.rmtree(src)
        src.symlink_to(target, target_is_directory=True)
        self.weave("b", "apply", "a", "test", ok=False)

    def test_duplicate_host_id_cannot_be_silently_claimed(self) -> None:
        self.skill("a", "mine", "# Mine\n")
        self.weave("a", "sync")
        third_hermes = self.root / "third" / ".hermes"
        third_hermes.mkdir(parents=True)
        self.weave("third", "init", "--host", "a", "--remote", str(self.remote),
                   "--hermes-home", str(third_hermes),
                   "--worktree", str(self.root / "third" / "data"), ok=False)
        self.assertFalse((self.root / "third" / "config.json").exists())
        self.assertTrue((self.root / "third" / "data" / ".git").is_dir())


if __name__ == "__main__":
    unittest.main()