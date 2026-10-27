"""AI-first CLI flows without external GitHub access or a real Hermes install."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE))


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

    def test_missing_init_options_fail_without_tty_instead_of_guessing(self) -> None:
        result = self.cli("init", ok=False)
        self.assertIn("interactive terminal", result.stderr)
        self.assertFalse(self.config.exists())

    def test_interactive_init_prompts_for_repo_instead_of_hardcoding(self) -> None:
        from hermes_weave.assistant import resolve_init_target
        with patch("hermes_weave.assistant.sys.stdin") as stdin, patch(
            "builtins.input", side_effect=["workstation", "1", "/srv/private-repo.git"]
        ):
            stdin.isatty.return_value = True
            self.assertEqual(resolve_init_target(None, None, None), ("workstation", "/srv/private-repo.git"))

    def test_interactive_repo_create_requires_explicit_confirmation(self) -> None:
        from hermes_weave.assistant import resolve_init_target
        from hermes_weave.cli import WeaveError
        with patch("hermes_weave.assistant.sys.stdin") as stdin, patch(
            "builtins.input", side_effect=["myhost", "2", "me/knowledge", "n"]
        ), patch("hermes_weave.assistant.github_repo") as create:
            stdin.isatty.return_value = True
            with self.assertRaisesRegex(WeaveError, "cancelled"):
                resolve_init_target(None, None, None)
            create.assert_not_called()

    def test_interactive_create_uses_user_selected_repo_and_noninteractive_flag(self) -> None:
        from hermes_weave.assistant import resolve_init_target
        payload = {"name": "me/anything", "created": True, "ssh_url": "git@github.com:me/anything.git"}
        with patch("hermes_weave.assistant.sys.stdin") as stdin, patch(
            "builtins.input", side_effect=["myhost", "2", "me/anything", "yes"]
        ), patch("hermes_weave.assistant.github_repo", return_value=payload) as create:
            stdin.isatty.return_value = True
            self.assertEqual(resolve_init_target(None, None, None), ("myhost", payload["ssh_url"]))
            create.assert_called_once_with("me/anything", create=True)
        # The explicit flag works in a headless Agent *after* it has user's approval.
        with patch("hermes_weave.assistant.sys.stdin") as stdin, patch(
            "hermes_weave.assistant.github_repo", return_value=payload
        ) as create:
            stdin.isatty.return_value = False
            self.assertEqual(resolve_init_target("myhost", None, "me/anything"), ("myhost", payload["ssh_url"]))
            create.assert_called_once_with("me/anything", create=True)

    def test_github_remote_privacy_is_checked(self) -> None:
        from hermes_weave.assistant import resolve_init_target
        from hermes_weave.cli import WeaveError
        with patch("hermes_weave.assistant.github_repo", side_effect=WeaveError("public repo")) as inspect:
            with self.assertRaisesRegex(WeaveError, "public repo"):
                resolve_init_target("laptop", "git@github.com:any-owner/any-repo.git", None)
            inspect.assert_called_once_with("any-owner/any-repo", create=False)

    def test_default_paths_use_hermes_weave_home(self) -> None:
        remote = self.root / "private.git"
        subprocess.run(["git", "init", "--bare", "--initial-branch=main", str(remote)], check=True, capture_output=True)
        seed = self.root / "seed"
        subprocess.run(["git", "init", "--initial-branch=main", str(seed)], check=True, capture_output=True)
        (seed / "README.md").write_text("Private Git test repo")
        for argv in [
            ["git", "-C", str(seed), "add", "README.md"],
            ["git", "-C", str(seed), "-c", "user.name=Test", "-c", "user.email=t@example.test", "commit", "-m", "seed"],
            ["git", "-C", str(seed), "remote", "add", "origin", str(remote)],
            ["git", "-C", str(seed), "push", "-u", "origin", "main"],
        ]:
            subprocess.run(argv, check=True, capture_output=True)
        proc = subprocess.run([sys.executable, "-S", "-m", "hermes_weave", "init", "--host", "test-host", "--remote", str(remote)],
                              capture_output=True, text=True, env=self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        home = self.root / ".hermes-weave"
        self.assertEqual(json.loads((home / "config.json").read_text())["worktree"], str(home / "data"))
        self.assertTrue((home / "state.json").is_file())
        self.assertTrue((home / "data" / ".git").is_dir())


if __name__ == "__main__":
    unittest.main()