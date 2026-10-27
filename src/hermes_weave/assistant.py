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


def github_slug_from_remote(remote: str) -> str | None:
    """Recognize GitHub remotes so we can verify they are PRIVATE before cloning."""
    match = (re.fullmatch(r"git@github\.com:([^/]+/[^/]+?)(?:\.git)?/?", remote)
             or re.fullmatch(r"https://github\.com/([^/]+/[^/]+?)(?:\.git)?/?", remote)
             or re.fullmatch(r"ssh://git@github\.com/([^/]+/[^/]+?)(?:\.git)?/?", remote))
    return match.group(1) if match and GITHUB_REPO_RE.fullmatch(match.group(1)) else None


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


def _prompt(question: str, default: str | None = None) -> str:
    label = f"{question} [{default}]: " if default else f"{question}: "
    try:
        answer = input(label).strip()
    except EOFError as exc:
        from .cli import WeaveError
        raise WeaveError("Initialization cancelled (input ended)") from exc
    return answer or (default or "")


def resolve_init_target(host: str | None, remote: str | None, create_repo: str | None) -> tuple[str, str]:
    """Resolve interactive choices or explicit flags; never invent a data remote.

    For a non-interactive Agent pass --host plus --remote/--create-repo
    *only after the user approves the named repository*.
    """
    from .cli import WeaveError, validate_host
    import socket

    if remote and create_repo:
        raise WeaveError("Choose --remote OR --create-repo, not both")
    if not host or (not remote and not create_repo):
        if not sys.stdin.isatty():
            raise WeaveError("Run 'weave init' in an interactive terminal, or pass --host plus --remote/--create-repo")
    if not host:
        suggestion = re.sub(r"[^a-z0-9-]+", "-", socket.gethostname().split(".", 1)[0].lower()).strip("-")[:48]
        default = suggestion if suggestion and re.fullmatch(r"[a-z][a-z0-9-]{0,47}", suggestion) else None
        host = _prompt("Unique host ID for THIS computer", default)
    validate_host(host)

    if not remote and not create_repo:
        print("Choose a PRIVATE data repository separate from the Hermes Weave source repository:")
        print("  1) Connect an existing Git repository")
        print("  2) Create a new PRIVATE GitHub repository (requires authenticated gh CLI)")
        choice = _prompt("Choose 1 or 2")
        if choice == "1":
            remote = _prompt("Existing Git URL or GitHub OWNER/REPO")
        elif choice == "2":
            create_repo = _prompt("New GitHub OWNER/REPO (no default name)")
            if not GITHUB_REPO_RE.fullmatch(create_repo):
                raise WeaveError("Invalid GitHub OWNER/REPO name")
            print(f"This creates {create_repo} as PRIVATE and initializes a README.")
            if _prompt("Create this remote repository? (y/N)").lower() not in ("y", "yes"):
                raise WeaveError("Repository creation cancelled")
        else:
            raise WeaveError("Choose 1 or 2; initialization cancelled")

    if create_repo:
        details = github_repo(create_repo, create=True)
        if not details.get("created"):
            raise WeaveError(f"Repository {create_repo} already exists; use --remote OWNER/REPO instead")
        remote = details["ssh_url"]
        print(f"Created PRIVATE GitHub data repository: {details['name']}")
    elif remote:
        slug = remote if GITHUB_REPO_RE.fullmatch(remote) else github_slug_from_remote(remote)
        if slug:
            details = github_repo(slug, create=False)
            if remote == slug:
                remote = details["ssh_url"]
            print(f"Verified PRIVATE GitHub data repository: {details['name']}")
    if not remote:
        raise WeaveError("A private Git remote is required")
    return host, remote


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