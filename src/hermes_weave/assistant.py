"""Human- and agent-friendly local setup helpers for Hermes Weave.

Changes to user files and remote repositories are explicit CLI subcommands.
Peer repository content is never executed by this module.
"""
from __future__ import annotations

import json
import os
from importlib.resources import files
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any
from uuid import uuid4


GITHUB_REPO_RE = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,38})/[a-zA-Z0-9_.-]{1,100}$")


def bundled_skill() -> bytes:
    """Bundled, audited skill; not fetched from arbitrary Git content."""
    return files("hermes_weave").joinpath("resources", "SKILL.md").read_bytes()


def skill_status(hermes_home: Path) -> dict[str, Any]:
    target = hermes_home / "skills" / "hermes-weave"
    skill = target / "SKILL.md"
    installed = skill.is_file() and not target.is_symlink() and not skill.is_symlink()
    current = installed and skill.read_bytes() == bundled_skill()
    return {"path": str(target), "installed": bool(installed), "current": bool(current)}


def install_skill(hermes_home: Path, replace: bool = False) -> str:
    from .cli import WeaveError, no_symlinks_below

    home = hermes_home.expanduser().absolute()
    if not home.is_dir() or home.is_symlink():
        raise WeaveError(f"Hermes home is missing or unsafe: {home}")
    dest = home / "skills" / "hermes-weave"
    no_symlinks_below(home, dest)
    desired = bundled_skill()
    if dest.exists():
        if not dest.is_dir():
            raise WeaveError(f"Not a directory: {dest}")
        source = dest / "SKILL.md"
        if source.is_file() and not source.is_symlink() and source.read_bytes() == desired:
            return f"Skill already installed: {dest}"
        if not replace:
            raise WeaveError(f"Skill already exists at {dest}; inspect it and explicitly pass --replace to back up and update")
    dest.parent.mkdir(parents=True, exist_ok=True)
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(prefix=".weave-skill-", dir=dest.parent) as temp:
        staged = Path(temp) / "hermes-weave"
        staged.mkdir()
        (staged / "SKILL.md").write_bytes(desired)
        if dest.exists():
            backup = dest.with_name(f"{dest.name}.weave-backup-{uuid4().hex[:8]}")
            dest.rename(backup)
            print(f"Previous skill backed up to {backup}")
        staged.rename(dest)
    return f"Installed Hermes Weave skill: {dest}. Start a new Hermes session to load it."


def doctor(config_file: Path, hermes_home: Path) -> dict[str, Any]:
    """Read-only local diagnostics safe to show to an Agent."""
    config_file = config_file.expanduser()
    cfg = None
    if config_file.is_file():
        try:
            cfg = json.loads(config_file.read_text(encoding="utf-8"))
            if not isinstance(cfg, dict):
                cfg = None
        except (OSError, ValueError):
            pass
    status = skill_status(hermes_home.expanduser()) if hermes_home.expanduser().is_dir() else {"installed": False, "current": False, "path": str(hermes_home.expanduser() / "skills" / "hermes-weave")}
    return {
        "python": sys.version.split()[0],
        "git_available": shutil.which("git") is not None,
        "gh_available": shutil.which("gh") is not None,
        "hermes_available": shutil.which("hermes") is not None,
        "hermes_home_exists": hermes_home.expanduser().is_dir(),
        "skill": status,
        "initialized": cfg is not None,
        "host": cfg.get("host") if cfg else None,
        "worktree_exists": Path(cfg.get("worktree", "")).expanduser().is_dir() if cfg else False,
        "share_memory": bool(cfg.get("share_memory", False)) if cfg else False,
    }


def github_repo(slug: str, create: bool = False) -> dict[str, Any]:
    """Inspect or explicitly create a GitHub PRIVATE DATA repository via gh CLI.

    This does not call shell=True; input is always passed as a single argv value.
    """
    from .cli import WeaveError
    if not GITHUB_REPO_RE.fullmatch(slug) or slug.split("/", 1)[-1].lower() == "hermes-weave":
        raise WeaveError("Provide OWNER/PRIVATE-DATA-REPOSITORY, separate from the hermes-weave source repository")
    if not shutil.which("gh"):
        raise WeaveError("GitHub CLI 'gh' is required; install it and authenticate with 'gh auth login'")

    def execute(*argv: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["gh", *argv], capture_output=True, text=True, check=False)

    def inspect() -> dict[str, Any] | None:
        result = execute("repo", "view", slug, "--json", "nameWithOwner,isPrivate,sshUrl,url")
        if result.returncode:
            return None
        try:
            data = json.loads(result.stdout)
        except ValueError as exc:
            raise WeaveError("Unexpected response from gh repo view") from exc
        if not data.get("isPrivate"):
            raise WeaveError(f"Refusing public data repository {slug}; create or select a PRIVATE one")
        return {"name": data["nameWithOwner"], "private": True, "ssh_url": data["sshUrl"], "https_url": data["url"] + ".git"}

    repo = inspect()
    if repo is not None:
        return {**repo, "created": False}
    if not create:
        raise WeaveError(f"Cannot inspect {slug}; check repository name/permissions or run 'weave repo create {slug}' after approval")
    result = execute("repo", "create", slug, "--private", "--add-readme", "--description", "Private Hermes Weave knowledge exchange data")
    if result.returncode:
        raise WeaveError(f"Private repo creation failed: {(result.stderr or result.stdout).strip()}")
    repo = inspect()
    if repo is None:
        raise WeaveError("Repository created but could not verify that it is private; inspect it before initializing")
    return {**repo, "created": True}
