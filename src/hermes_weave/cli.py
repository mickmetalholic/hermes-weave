"""Safe-by-default, Git-backed exchange of Hermes skills and optional snapshots.

Every host owns only hosts/<host> in a separate *private data repository*.
Incoming skills are reviewed and installed explicitly; memory and config are
never applied automatically. No LLM or remote content is executed by this CLI.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any
from uuid import uuid4

SCHEMA = 1
HOST_RE = re.compile(r"^[a-z][a-z0-9-]{0,47}$")
SKILL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
SKIP_NAMES = {".git", ".env", "auth.json", "state.db", ".ssh", "node_modules", "__pycache__", "secrets", "credentials.json"}
SKIP_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".sqlite", ".db", ".pyc")
SENSITIVE = (
    re.compile(rb"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----"),
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(rb"\bAKIA[A-Z0-9]{16}\b"),
    re.compile(rb"(?i)\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)\s*[:=]\s*['\"]?[A-Za-z0-9+/_=-]{12,}"),
)
MAX_FILE = 256 * 1024
MAX_SKILL = 1024 * 1024


class WeaveError(Exception):
    """User-actionable error. No traceback from the CLI."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def atomic_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".weave-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump(obj, fp, indent=2, sort_keys=True)
            fp.write("\n")
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def read_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        if default is not None:
            return default
        raise WeaveError(f"Missing {path}; run 'weave init' first")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise WeaveError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise WeaveError(f"Expected JSON object in {path}")
    return data


def run_git(repo: Path | None, *argv: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = ["git"] + (["-C", str(repo)] if repo else []) + list(argv)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise WeaveError("git is not installed") from exc
    if check and result.returncode:
        raise WeaveError(f"git {' '.join(argv)} failed: {(result.stderr or result.stdout).strip()}")
    return result


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def forbidden(path: Path) -> bool:
    return any(p in SKIP_NAMES or p.startswith(".env") or p.endswith(SKIP_SUFFIXES)
               for p in path.parts)


def checked_files(directory: Path) -> list[tuple[Path, bytes]]:
    if directory.is_symlink() or not directory.is_dir():
        raise WeaveError(f"Not a regular directory: {directory}")
    result: list[tuple[Path, bytes]] = []
    total = 0
    for root, dirs, files in os.walk(directory, followlinks=False):
        root_path = Path(root)
        for item in dirs + files:
            child = root_path / item
            rel = child.relative_to(directory)
            if child.is_symlink() or forbidden(rel):
                raise WeaveError(f"Unsafe or excluded path in {directory.name}: {rel}")
        for name in sorted(files):
            path = root_path / name
            rel = path.relative_to(directory)
            if not path.is_file() or path.stat().st_size > MAX_FILE:
                raise WeaveError(f"Non-regular/oversized file: {path}")
            data = path.read_bytes()
            total += len(data)
            if total > MAX_SKILL or b"\0" in data or any(p.search(data) for p in SENSITIVE):
                raise WeaveError(f"Possible secret, binary, or oversized skill: {directory.name}/{rel}")
            result.append((rel, data))
    if not any(rel == Path("SKILL.md") for rel, _ in result):
        raise WeaveError(f"No SKILL.md in {directory.name}")
    return sorted(result, key=lambda item: str(item[0]))


def skill_hash(directory: Path) -> str:
    digest = hashlib.sha256()
    for rel, content in checked_files(directory):
        digest.update(rel.as_posix().encode("utf-8") + b"\0" + content + b"\0")
    return digest.hexdigest()


def config_path(args: argparse.Namespace) -> Path:
    return Path(args.config).expanduser().resolve()


def load_config(args: argparse.Namespace) -> dict[str, Any]:
    cfg = read_json(config_path(args))
    host = cfg.get("host", "")
    if not isinstance(host, str) or not HOST_RE.fullmatch(host):
        raise WeaveError("Invalid host in configuration")
    return cfg


def repo_path(cfg: dict[str, Any]) -> Path:
    return Path(cfg["worktree"]).expanduser().resolve()


def hermes_path(cfg: dict[str, Any]) -> Path:
    return Path(cfg["hermes_home"]).expanduser().resolve()


def state_path(args: argparse.Namespace) -> Path:
    return config_path(args).with_name("state.json")


@contextmanager
def exclusive(args: argparse.Namespace):
    lock = config_path(args).with_name("sync.lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a+") as fp:
        try:
            fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise WeaveError("Another weave command is running; try again later") from exc
        yield


def ensure_clean(repo: Path) -> None:
    result = run_git(repo, "status", "--porcelain", "--untracked-files=all")
    if result.stdout.strip():
        raise WeaveError("Data worktree has uncommitted changes. Resolve them manually before syncing.")


def pull_git(cfg: dict[str, Any]) -> None:
    repo = repo_path(cfg)
    branch = cfg["branch"]
    ensure_clean(repo)
    run_git(repo, "fetch", "origin", branch)
    rebased = run_git(repo, "rebase", f"origin/{branch}", check=False)
    if rebased.returncode:
        run_git(repo, "rebase", "--abort", check=False)
        raise WeaveError("Cannot rebase local data commits; inspect the data worktree manually")


def push_git(cfg: dict[str, Any]) -> None:
    repo = repo_path(cfg)
    branch = cfg["branch"]
    for attempt in range(4):
        pushed = run_git(repo, "push", "origin", f"HEAD:{branch}", check=False)
        if pushed.returncode == 0:
            return
        # Disjoint host directories generally rebase cleanly after a racing push.
        run_git(repo, "fetch", "origin", branch)
        rebased = run_git(repo, "rebase", f"origin/{branch}", check=False)
        if rebased.returncode:
            run_git(repo, "rebase", "--abort", check=False)
            raise WeaveError("Rebase conflict. Data was NOT overwritten; inspect Git history before retrying.")
    raise WeaveError("Push rejected repeatedly (concurrent writers?); retry later")


def validate_host(value: str) -> str:
    if not HOST_RE.fullmatch(value):
        raise WeaveError("Host must be lowercase, start with a-z, and contain only a-z, 0-9 or - (max 48)")
    return value


def validate_skill(value: str) -> str:
    """Accept categorized skills like devops/deploy but never traversal."""
    parts = value.split("/")
    if not parts or any(not SKILL_RE.fullmatch(part) or part in (".", "..") for part in parts):
        raise WeaveError("Invalid skill path")
    return value


def no_symlinks_below(base: Path, target: Path) -> None:
    """Refuse paths through symlinked ancestors in a writable/untrusted tree."""
    try:
        parts = target.relative_to(base).parts
    except ValueError as exc:
        raise WeaveError(f"Unsafe path outside {base}: {target}") from exc
    cursor = base
    if cursor.is_symlink():
        raise WeaveError(f"Unsafe symlink: {cursor}")
    for part in parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise WeaveError(f"Unsafe symlink: {cursor}")


def skill_directories(root: Path) -> list[tuple[str, Path]]:
    """Hermes supports optional category directories, e.g. devops/deploy."""
    if not root.exists() or root.is_symlink():
        return []
    result = []
    for skill_file in root.rglob("SKILL.md"):
        folder = skill_file.parent
        rel = folder.relative_to(root).as_posix()
        try:
            validate_skill(rel)
        except WeaveError:
            continue
        result.append((rel, folder))
    return sorted(result)


def init(args: argparse.Namespace) -> None:
    host = validate_host(args.host)
    dest = Path(args.worktree).expanduser().resolve()
    home = Path(args.hermes_home).expanduser().resolve()
    config_file = config_path(args)
    if config_file.exists():
        raise WeaveError(f"Configuration already exists: {config_file}")
    if dest.exists():
        raise WeaveError(f"Worktree must not exist yet: {dest}")
    if not home.is_dir():
        raise WeaveError(f"Hermes home does not exist: {home}")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9/_-]{0,95}", args.branch) or ".." in args.branch or "//" in args.branch:
        raise WeaveError("Invalid branch name")
    dest.parent.mkdir(parents=True, exist_ok=True)
    run_git(None, "clone", "--branch", args.branch, "--single-branch", "--", args.remote, str(dest))
    cfg = {"schema": SCHEMA, "host": host, "remote": args.remote, "branch": args.branch,
           "worktree": str(dest), "hermes_home": str(home),
           "share_memory": bool(args.share_memory),
           "shared_config_file": str(Path(args.shared_config).expanduser().resolve()) if args.shared_config else None}
    atomic_json(config_file, cfg)
    atomic_json(state_path(args), {"schema": SCHEMA, "imports": {}})
    print(f"Initialized node {host}. Worktree: {dest}\nNext: weave sync")


def export(cfg: dict[str, Any], args: argparse.Namespace) -> int:
    repo = repo_path(cfg)
    host = cfg["host"]
    hosts_base = repo / "hosts"
    root = hosts_base / host
    if hosts_base.is_symlink() or root.is_symlink():
        raise WeaveError("Unsafe symlink in data repository host namespace")
    skills_root = hermes_path(cfg) / "skills"
    state = read_json(state_path(args), {"imports": {}})
    imports = state.get("imports", {})
    if not isinstance(imports, dict):
        raise WeaveError("Invalid import ledger")
    result: dict[str, list[tuple[Path, bytes]]] = {}
    rejected: list[str] = []
    if skills_root.is_symlink():
        raise WeaveError("Refusing symlinked local skills directory")
    if skills_root.is_dir():
        for skill_name, skill in skill_directories(skills_root):
            if skill_name in imports:  # Never re-export imported content as an original.
                continue
            try:
                result[skill_name] = checked_files(skill)
            except WeaveError as exc:
                rejected.append(f"{skill_name}: {exc}")
    for warning in rejected:
        print(f"SKIPPED: {warning}", file=sys.stderr)

    # Never remove the previously published version of a rejected skill.
    previous = root / "skills"
    if previous.exists():
        for name in rejected:
            skill = name.split(":", 1)[0]
            original = previous / skill
            if original.is_dir():
                try:
                    result[skill] = checked_files(original)
                except WeaveError:
                    pass

    snapshot: dict[str, bytes] = {}
    for name, files in result.items():
        for rel, content in files:
            snapshot[f"skills/{name}/{rel.as_posix()}"] = content

    if cfg.get("share_memory"):
        memory_root = hermes_path(cfg) / "memories"
        for filename in ("MEMORY.md", "USER.md"):
            source = memory_root / filename
            if source.is_file() and not source.is_symlink():
                data = source.read_bytes()
                if len(data) > MAX_FILE or b"\0" in data or any(p.search(data) for p in SENSITIVE):
                    raise WeaveError(f"Unsafe memory snapshot: {source}")
                snapshot[f"memory/{filename}"] = data

    if cfg.get("shared_config_file"):
        source = Path(cfg["shared_config_file"])
        if not source.is_file() or source.is_symlink():
            raise WeaveError(f"Missing regular shared config file: {source}")
        data = source.read_bytes()
        if len(data) > MAX_FILE or b"\0" in data or any(p.search(data) for p in SENSITIVE):
            raise WeaveError("Shared config looks sensitive; redact it before publishing")
        snapshot["config/shared.yaml"] = data

    previous_manifest = read_json(root / "manifest.json", {})
    files_hash = {key: sha256(value) for key, value in sorted(snapshot.items())}
    if previous_manifest.get("files") == files_hash:
        print(f"No snapshot changes for {host} ({len(result)} skills)")
        return len(result)

    # Replace only this host's snapshot; other hosts are NEVER modified here.
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    for rel, content in snapshot.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    (root / "manifest.json").write_text(json.dumps({"schema": SCHEMA, "host": host,
        "published_at": now(), "files": files_hash}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return len(result)


def publish(cfg: dict[str, Any], args: argparse.Namespace) -> None:
    pull_git(cfg)
    count = export(cfg, args)
    repo = repo_path(cfg)
    own = f"hosts/{cfg['host']}"
    run_git(repo, "add", "--", own)
    staged = run_git(repo, "diff", "--cached", "--quiet", "--", own, check=False)
    if staged.returncode not in (0, 1):
        raise WeaveError("Cannot inspect staged changes")
    if staged.returncode == 1:
        run_git(repo, "-c", "user.name=Hermes Weave", "-c", "user.email=weave@localhost",
                "commit", "-m", f"weave({cfg['host']}): publish snapshot", "--", own)
    push_git(cfg)
    print(f"Published {count} local skills from {cfg['host']}")


def collect_reviews(cfg: dict[str, Any], args: argparse.Namespace) -> list[dict[str, Any]]:
    hosts_dir = repo_path(cfg) / "hosts"
    if hosts_dir.is_symlink():
        raise WeaveError("Unsafe symlink in data repository host namespace")
    state = read_json(state_path(args), {"imports": {}})
    imported = state.get("imports", {})
    reviews = []
    if not hosts_dir.exists():
        return reviews
    for host_dir in sorted(hosts_dir.iterdir()):
        if not host_dir.is_dir() or host_dir.is_symlink() or host_dir.name == cfg["host"]:
            continue
        if not HOST_RE.fullmatch(host_dir.name):
            continue
        entries = []
        for skill_name, src in skill_directories(host_dir / "skills"):
            try:
                digest = skill_hash(src)
            except WeaveError:
                continue
            key = f"{host_dir.name}/{skill_name}"
            record = next((r for r in imported.values() if r.get("source") == key), None)
            dest = hermes_path(cfg) / "skills" / (record["dest"] if record else skill_name)
            if record:
                try:
                    local_hash = skill_hash(dest) if dest.is_dir() else ""
                except WeaveError:
                    local_hash = ""
                status = "local-modified" if local_hash != record.get("installed_hash") else ("installed" if digest == record.get("source_hash") else "update")
            else:
                status = "conflict" if dest.exists() else "new"
            entries.append({"skill": skill_name, "source": key, "sha256": digest, "status": status})
        memory = [p.name for p in (host_dir / "memory").glob("*.md") if p.is_file() and not p.is_symlink()]
        reviews.append({"host": host_dir.name, "skills": entries, "memory": sorted(memory),
                        "shared_config": (host_dir / "config" / "shared.yaml").is_file()})
    return reviews


def review(cfg: dict[str, Any], args: argparse.Namespace) -> None:
    results = collect_reviews(cfg, args)
    if args.json:
        print(json.dumps({"host": cfg["host"], "peers": results}, indent=2))
        return
    if not results:
        print("No remote hosts found. Run 'weave pull' after another host publishes.")
    for item in results:
        print(f"{item['host']}: {len(item['skills'])} skills; memory={','.join(item['memory']) or '-'}; config={'yes' if item['shared_config'] else 'no'}")
        for skill in item["skills"]:
            print(f"  {skill['status']:15} {skill['skill']}")
    print("Review sources before using 'weave apply HOST SKILL'. Memory/config are never applied automatically.")


def apply_skill(cfg: dict[str, Any], args: argparse.Namespace) -> None:
    host = validate_host(args.host)
    skill = validate_skill(args.skill)
    name = validate_skill(args.as_name or skill)
    if host == cfg["host"]:
        raise WeaveError("Cannot import your own host snapshot")
    src = repo_path(cfg) / "hosts" / host / "skills" / skill
    no_symlinks_below(repo_path(cfg), src)
    files = checked_files(src)
    digest = skill_hash(src)
    skill_root = hermes_path(cfg) / "skills"
    target = skill_root / name
    no_symlinks_below(hermes_path(cfg), target)
    state = read_json(state_path(args), {"schema": SCHEMA, "imports": {}})
    imported = state.setdefault("imports", {})
    if target.is_symlink():
        raise WeaveError("Refusing to overwrite a symlink")
    if target.exists():
        if not args.replace:
            raise WeaveError(f"{target} already exists. Use --as NEW_NAME or explicit --replace")
        if not target.is_dir():
            raise WeaveError(f"Target is not a directory: {target}")
        # Don't overwrite a different host's imported skill, even with --replace.
        if name in imported and imported[name].get("source") != f"{host}/{skill}":
            raise WeaveError("Destination belongs to a different peer; use --as")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".weave-import-", dir=target.parent) as tmp:
        staged = Path(tmp) / name
        for rel, data in files:
            if rel == Path("SKILL.md") and name != skill:
                text = data.decode("utf-8")
                # Keep frontmatter identity consistent with --as, without touching the remote source.
                if text.startswith("---\n"):
                    header, separator, rest = text[4:].partition("\n---")
                    if separator:
                        header = re.sub(r"(?m)^(name:[ \t]*)[^\n]+", lambda m: m.group(1) + name.rsplit("/", 1)[-1], header, count=1)
                        data = ("---\n" + header + separator + rest).encode("utf-8")
            dest = staged / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        if target.exists():
            backup = target.with_name(f"{target.name}.weave-backup-{uuid4().hex[:8]}")
            target.rename(backup)
            print(f"Backup saved to {backup}")
        staged.rename(target)
    imported[name] = {"source": f"{host}/{skill}", "dest": name, "source_hash": digest,
                      "installed_hash": skill_hash(target), "installed_at": now()}
    atomic_json(state_path(args), state)
    print(f"Imported {host}/{skill} -> {target}. Review SKILL.md before enabling/using it.")


def promote(cfg: dict[str, Any], args: argparse.Namespace) -> None:
    name = validate_skill(args.skill)
    state = read_json(state_path(args), {"schema": SCHEMA, "imports": {}})
    if name not in state.get("imports", {}):
        raise WeaveError("Skill is not an imported skill")
    del state["imports"][name]
    atomic_json(state_path(args), state)
    print(f"Promoted {name} to a locally owned skill; next publish may share it")


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(prog="weave", description="Safe knowledge exchange among independent Hermes agents")
    cli.add_argument("--config", default="~/.config/hermes-weave/config.json", help="Local CLI configuration path")
    sub = cli.add_subparsers(dest="command", required=True)
    init_cmd = sub.add_parser("init", help="Register a unique host and clone the PRIVATE DATA repository")
    init_cmd.add_argument("--host", required=True)
    init_cmd.add_argument("--remote", required=True, help="Separate private DATA Git remote (not the source-code repo)")
    init_cmd.add_argument("--branch", default="main")
    init_cmd.add_argument("--hermes-home", default="~/.hermes")
    init_cmd.add_argument("--worktree", default="~/.local/share/hermes-weave/data")
    init_cmd.add_argument("--share-memory", action="store_true", help="Opt-in to publishing private MEMORY.md and USER.md")
    init_cmd.add_argument("--shared-config", help="Explicitly curated and redacted YAML file to publish (NOT Hermes config.yaml)")
    sub.add_parser("pull", help="Fetch peers without applying anything to Hermes")
    sub.add_parser("publish", help="Publish only this host's safe snapshot to Git")
    sub.add_parser("sync", help="Pull, publish, then summarize peers (no automatic imports)")
    rev = sub.add_parser("review", help="Inspect new/updated peer skills and available snapshots")
    rev.add_argument("--json", action="store_true", help="Machine-readable output for Hermes Agent")
    app = sub.add_parser("apply", help="Explicitly import ONE reviewed peer skill")
    app.add_argument("host")
    app.add_argument("skill")
    app.add_argument("--as", dest="as_name", help="Local destination skill name")
    app.add_argument("--replace", action="store_true", help="Back up and overwrite existing destination")
    promote_cmd = sub.add_parser("promote", help="Explicitly fork an imported skill into a locally owned skill")
    promote_cmd.add_argument("skill")
    return cli


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        with exclusive(args):
            if args.command == "init":
                init(args)
                return 0
            cfg = load_config(args)
            if args.command == "pull":
                pull_git(cfg)
                print("Fetched peers; local Hermes unchanged")
            elif args.command == "publish":
                publish(cfg, args)
            elif args.command == "sync":
                publish(cfg, args)
                review(cfg, argparse.Namespace(**{**vars(args), "json": False}))
            elif args.command == "review":
                review(cfg, args)
            elif args.command == "apply":
                apply_skill(cfg, args)
            elif args.command == "promote":
                promote(cfg, args)
        return 0
    except (WeaveError, OSError, KeyError) as exc:
        print(f"weave: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
