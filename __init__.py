"""Hermes Weave native plugin entry point.

Hermes imports this package from the repository root after explicit enablement.
The Git data and local state are stored OUTSIDE the plugin install directory.
"""
from pathlib import Path

from . import schemas, tools


def register(ctx):
    """Register model tools, a safe slash command, a CLI bridge, and a Skill."""
    for schema, handler in (
        (schemas.STATUS, tools.status),
        (schemas.REVIEW, tools.review),
        (schemas.PULL, tools.pull),
        (schemas.INIT, tools.initialize),
        (schemas.SYNC, tools.sync),
        (schemas.APPLY, tools.apply),
    ):
        ctx.register_tool(
            name=schema["name"],
            toolset="weave",
            schema=schema,
            handler=handler,
        )

    ctx.register_skill(
        "hermes-weave",
        Path(__file__).parent / "skills" / "hermes-weave" / "SKILL.md",
    )
    ctx.register_command(
        "weave",
        handler=tools.slash_command,
        description="Check Hermes Weave status or peer reviews (read-only)",
        args_hint="[status|review]",
    )
    ctx.register_cli_command(
        name="weave",
        help="Manage Hermes Weave Git-based agent knowledge sync",
        setup_fn=tools.setup_cli_parser,
        handler_fn=tools.cli_command,
    )
