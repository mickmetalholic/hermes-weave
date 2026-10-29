"""Native Hermes plugin tool handlers backed by the existing Weave CLI.

The CLI runs as a bounded subprocess with no shell, using this plugin's bundled
src/ tree. This avoids mutating the gateway's sys.path or capturing process-wide
stdout and lets Hermes load Weave without pip-installing a second CLI.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys


_ROOT = Path(__file__).resolve().parent
_SOURCE = _ROOT / "src"
_MAX_OUTPUT = 24_000
_SECRET_PATTERNS = (
    re.compile(r"(?i)(https?://)[^/@\s]+:[^/@\s]+@"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{12,}|sk-[A-Za-z0-9_-]{20,})\b"),
)


def _sanitize(value: str) -> str:
    value = _SECRET_PATTERNS[0].sub(r"\1[REDACTED]@", value)
    return _SECRET_PATTERNS[1].sub("[REDACTED]", value)


def _json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _invoke(arguments: list[str], *, timeout: int = 120) -> dict:
    """Run a supported CLI argv vector. No shell/command string evaluation."""
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        item for item in (str(_SOURCE), env.get("PYTHONPATH", "")) if item
    )
    command = [sys.executable, "-m", "hermes_weave", *arguments]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
            cwd=str(Path.home()),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Weave operation timed out after {timeout}s"}
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": f"Cannot launch Weave CLI: {type(exc).__name__}"}

    # Bound tool messages; do not return raw unbounded Git logs to the Agent.
    stdout = _sanitize(result.stdout[:_MAX_OUTPUT])
    stderr = _sanitize(result.stderr[:4096])
    answer = {"ok": result.returncode == 0, "exit_code": result.returncode}
    if stdout:
        try:
            answer["data"] = json.loads(stdout)
        except ValueError:
            answer["output"] = stdout
    if stderr:
        answer["error"] = stderr
    if len(result.stdout) > _MAX_OUTPUT:
        answer["truncated"] = True
    return answer


def _approved(params: dict, action: str) -> str | None:
    if params.get("user_approved") is not True:
        return _json({
            "ok": False,
            "needs_user_approval": True,
            "error": f"Ask the user for explicit approval before {action}.",
        })
    return None


def status(params: dict, **kwargs) -> str:
    return _json(_invoke(["doctor", "--json"], timeout=20))


def review(params: dict, **kwargs) -> str:
    return _json(_invoke(["review", "--json"], timeout=25))


def pull(params: dict, **kwargs) -> str:
    if (error := _approved(params, "fetching remote Git data")):
        return error
    return _json(_invoke(["pull"], timeout=120))


def initialize(params: dict, **kwargs) -> str:
    if (error := _approved(params, "initializing this machine or creating a data repository")):
        return error
    host = params.get("host")
    remote = params.get("remote")
    create_repo = params.get("create_repo")
    if not isinstance(host, str) or not host:
        return _json({"ok": False, "error": "Unique host ID is required."})
    if bool(remote) == bool(create_repo):
        return _json({"ok": False, "error": "Supply exactly one approved remote or create_repo."})
    target = remote if remote else create_repo
    if not isinstance(target, str) or not target.strip():
        return _json({"ok": False, "error": "Invalid repository value."})
    argv = ["init", "--host", host, "--remote" if remote else "--create-repo", target]
    # Never expose share-memory in the Agent tool. Explicit CLI opt-in is available.
    return _json(_invoke(argv, timeout=180))


def sync(params: dict, **kwargs) -> str:
    if (error := _approved(params, "publishing this host's selected knowledge to Git")):
        return error
    return _json(_invoke(["sync"], timeout=240))


def apply(params: dict, **kwargs) -> str:
    if (error := _approved(params, "importing the reviewed peer Skill")):
        return error
    host, skill = params.get("host"), params.get("skill")
    if not isinstance(host, str) or not host or not isinstance(skill, str) or not skill:
        return _json({"ok": False, "error": "Both source host and Skill name are required."})
    argv = ["apply", host, skill]
    alias = params.get("as_name")
    if alias is not None:
        if not isinstance(alias, str) or not alias:
            return _json({"ok": False, "error": "Invalid alternate Skill name."})
        argv.extend(["--as", alias])
    if params.get("replace") is True:
        # Replacement has a distinct risk, even with a backup. The user must
        # explicitly consent to the overwrite in addition to the import.
        if params.get("replace_approved") is not True:
            return _json({
                "ok": False,
                "needs_user_approval": True,
                "error": "Explicitly approve overwriting the existing Skill before using --replace.",
            })
        argv.append("--replace")
    return _json(_invoke(argv, timeout=60))


def slash_command(raw_args: str, **kwargs) -> str:
    """Only read-only operations are available through /weave."""
    choice = (raw_args or "").strip()
    if choice in ("", "help"):
        return "Hermes Weave: /weave status or /weave review. Other operations use Agent tools or 'hermes weave'."
    if choice == "status":
        return status({})
    if choice == "review":
        return review({})
    return "Unsupported /weave action. Use /weave status or /weave review (read-only)."


def setup_cli_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "weave_args",
        nargs=argparse.REMAINDER,
        help="Weave CLI subcommand and flags (init, sync, review, apply, doctor...)",
    )


def cli_command(args: argparse.Namespace) -> None:
    """Forward terminal 'hermes weave ...' to the unchanged CLI.

    This is intentionally NOT exposed as an unrestricted Agent tool.
    """
    argv = list(getattr(args, "weave_args", []) or [])
    if argv and argv[0] == "--":
        argv.pop(0)
    if not argv:
        argv = ["doctor", "--json"]
    result = _invoke(argv, timeout=240)
    if "data" in result:
        print(json.dumps(result["data"], ensure_ascii=False, indent=2))
    if "output" in result:
        print(result["output"])
    if not result["ok"]:
        print(result.get("error", f"weave exited with {result.get('exit_code', 'error')}"), file=sys.stderr)
