"""AI-first CLI flows without external GitHub access or a real Hermes install."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "src"


class AISetupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.hermes = self.root / ".hermes"
        self.hermes.mkdir()
        self.config = self.root / "weave-config.json"
        self.env = {**os.environ, "HOME": str(self.root), "PYTHONPATH": str(SOURCE)}

    def cli(self, *args: str, ok: bool = True) -> subprocess.CompletedProcess[str]:
        cmd = [sys.executable, "-S", "-m", "hermes_weave", "--config", str(self.config), *args]
        proc = subprocess.run(cmd, capture_output=True, text=True, env=self.env)
        if ok:
            self.assertEqual(proc.returncode, 0, proc.stderr)
        else:
            self.assertNotEqual(proc.returncode, 0, proc.stdout)
        return proc

    def test_skill_install_is_idempotent_and_doctor_reports_status(self) -> None:
        self.cli("skill", "install", "--hermes-home", str(self.hermes))
        skill = self.hermes / "skills" / "hermes-weave" / "SKILL.md"
        self.assertTrue(skill.is_file())
        original = skill.read_bytes()
        self.assertEqual(self.cli("skill", "install", "--hermes-home", str(self.hermes)).returncode, 0)
        self.assertEqual(skill.read_bytes(), original)
        info = json.loads(self.cli("doctor", "--json").stdout)
        self.assertTrue(info["skill"]["current"])
        self.assertFalse(info["initialized"])
        self.assertTrue(info["git_available"])

    def test_skill_install_refuses_overwrite_without_replace(self) -> None:
        target = self.hermes / "skills" / "hermes-weave"
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text("My custom Skill\n")
        self.cli("skill", "install", "--hermes-home", str(self.hermes), ok=False)
        self.assertEqual((target / "SKILL.md").read_text(), "My custom Skill\n")
        self.cli("skill", "install", "--hermes-home", str(self.hermes), "--replace")
        self.assertIn("name: hermes-weave", (target / "SKILL.md").read_text())
        backups = list(target.parent.glob("hermes-weave.weave-backup-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "SKILL.md").read_text(), "My custom Skill\n")

    def test_skill_install_refuses_symlinked_skills_directory(self) -> None:
        external = self.root / "elsewhere"
        external.mkdir()
        (self.hermes / "skills").symlink_to(external, target_is_directory=True)
        self.cli("skill", "install", "--hermes-home", str(self.hermes), ok=False)
        self.assertEqual(list(external.iterdir()), [])

    def test_repo_create_requires_valid_name_and_private_repository(self) -> None:
        gh = self.root / "bin" / "gh"
        gh.parent.mkdir()
        gh.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
flag = Path(os.environ["FAKE_GH_CREATED"])
repo = args[2]
if args[:2] == ["repo", "view"]:
    if repo.endswith("/public"):
        print(json.dumps({"nameWithOwner":repo,"isPrivate":False,"sshUrl":"git@example.com:public","url":"https://github.com/owner/public"}))
    elif flag.exists():
        print(json.dumps({"nameWithOwner":repo,"isPrivate":True,"sshUrl":"git@github.com:"+repo+".git","url":"https://github.com/"+repo}))
    else:
        sys.exit(1)
elif args[:2] == ["repo", "create"]:
    if "--private" not in args or "--add-readme" not in args:
        sys.exit(12)
    flag.write_text(repo)
else:
    sys.exit(5)
''')
        gh.chmod(0o755)
        self.env["PATH"] = str(gh.parent) + os.pathsep + self.env.get("PATH", "")
        self.env["FAKE_GH_CREATED"] = str(self.root / "created")
        self.cli("repo", "inspect", "owner/data", ok=False)
        created = json.loads(self.cli("repo", "create", "owner/data").stdout)
        self.assertTrue(created["created"])
        self.assertEqual(created["ssh_url"], "git@github.com:owner/data.git")
        existing = json.loads(self.cli("repo", "inspect", "owner/data").stdout)
        self.assertFalse(existing["created"])
        self.cli("repo", "inspect", "owner/public", ok=False)
        self.cli("repo", "create", "owner/hermes-weave", ok=False)
        self.cli("repo", "create", "owner/invalid;touch-anything", ok=False)

    def test_init_does_not_clone_source_repo_or_store_token(self) -> None:
        self.cli("init", "--host", "laptop", "--remote", "git@github.com:mickmetalholic/hermes-weave.git", ok=False)
        self.cli("init", "--host", "laptop", "--remote", "https://user:example@github.com/acme/data.git", ok=False)
        self.assertFalse(self.config.exists())


if __name__ == "__main__":
    unittest.main()
