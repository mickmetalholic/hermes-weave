"""Contract tests for the native Hermes plugin, without importing Hermes core."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "weave_plugin_under_test", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)]
)
assert SPEC and SPEC.loader
PLUGIN = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PLUGIN
SPEC.loader.exec_module(PLUGIN)
TOOLS = PLUGIN.tools


class FakeHermesContext:
    def __init__(self):
        self.tools = {}
        self.skills = {}
        self.commands = {}
        self.cli_commands = {}

    def register_tool(self, **kwargs):
        self.tools[kwargs["name"]] = kwargs

    def register_skill(self, name, path):
        self.skills[name] = path

    def register_command(self, name, handler, **kwargs):
        self.commands[name] = handler

    def register_cli_command(self, name, help, setup_fn, handler_fn):
        self.cli_commands[name] = (setup_fn, handler_fn)


class NativePluginTests(unittest.TestCase):
    def test_register_all_tools_and_namespaced_skill(self):
        ctx = FakeHermesContext()
        PLUGIN.register(ctx)
        self.assertEqual(
            set(ctx.tools),
            {"weave_status", "weave_review", "weave_pull", "weave_init", "weave_sync", "weave_apply"},
        )
        for name, entry in ctx.tools.items():
            self.assertEqual(name, entry["schema"]["name"])
            self.assertEqual(entry["toolset"], "weave")
            self.assertTrue(callable(entry["handler"]))
        self.assertIn("hermes-weave", ctx.skills)
        self.assertTrue(ctx.skills["hermes-weave"].is_file())
        self.assertIn("weave", ctx.commands)
        self.assertIn("weave", ctx.cli_commands)

    def test_status_and_review_read_only(self):
        with patch.object(TOOLS, "_invoke", return_value={"ok": True, "data": {"peers": []}}) as invoke:
            self.assertTrue(json.loads(TOOLS.status({}))["ok"])
            self.assertTrue(json.loads(TOOLS.review({}))["ok"])
            self.assertEqual(invoke.call_args_list[0].args[0], ["doctor", "--json"])
            self.assertEqual(invoke.call_args_list[1].args[0], ["review", "--json"])

    def test_mutations_require_explicit_flag(self):
        with patch.object(TOOLS, "_invoke") as invoke:
            for func, args in (
                (TOOLS.pull, {}),
                (TOOLS.sync, {}),
                (TOOLS.initialize, {"host": "host-a", "remote": "example/private"}),
                (TOOLS.apply, {"host": "host-a", "skill": "demo"}),
            ):
                response = json.loads(func(args))
                self.assertFalse(response["ok"])
                self.assertTrue(response["needs_user_approval"])
            invoke.assert_not_called()

    def test_init_passes_no_memory_opt_in_or_shell(self):
        with patch.object(TOOLS, "_invoke", return_value={"ok": True}) as invoke:
            result = json.loads(TOOLS.initialize({
                "host": "macbook", "remote": "owner/private", "user_approved": True
            }))
            self.assertTrue(result["ok"])
            self.assertEqual(
                invoke.call_args.args[0],
                ["init", "--host", "macbook", "--remote", "owner/private"],
            )
            self.assertFalse(json.loads(TOOLS.initialize({
                "host": "macbook", "remote": "x", "create_repo": "y", "user_approved": True
            }))["ok"])
            self.assertEqual(invoke.call_count, 1)

    def test_apply_does_not_replace_without_separate_approval(self):
        with patch.object(TOOLS, "_invoke", return_value={"ok": True}) as invoke:
            no = json.loads(TOOLS.apply({
                "host": "another", "skill": "code-review", "user_approved": True, "replace": True
            }))
            self.assertFalse(no["ok"])
            self.assertTrue(no["needs_user_approval"])
            invoke.assert_not_called()
            yes = json.loads(TOOLS.apply({
                "host": "another", "skill": "code-review", "user_approved": True,
                "replace": True, "replace_approved": True
            }))
            self.assertTrue(yes["ok"])
            self.assertEqual(invoke.call_args.args[0], ["apply", "another", "code-review", "--replace"])

    def test_subprocess_is_argv_only_and_uses_bundled_src(self):
        mocked = subprocess.CompletedProcess(["python"], 0, '{"host": "a"}\n', "")
        with patch.object(TOOLS.subprocess, "run", return_value=mocked) as run:
            res = TOOLS._invoke(["doctor", "--json"])
            self.assertTrue(res["ok"])
            self.assertEqual(res["data"]["host"], "a")
            called = run.call_args
            self.assertEqual(called.args[0][1:3], ["-m", "hermes_weave"])
            self.assertIn(str(ROOT / "src"), called.kwargs["env"]["PYTHONPATH"])
            self.assertEqual(called.kwargs["cwd"], str(Path.home()))
            self.assertNotIn("shell", called.kwargs)

    def test_subprocess_timeouts_are_reported(self):
        with patch.object(TOOLS.subprocess, "run", side_effect=subprocess.TimeoutExpired("weave", 5)):
            result = TOOLS._invoke(["pull"], timeout=5)
        self.assertFalse(result["ok"])
        self.assertIn("timed out", result["error"])

    def test_slash_command_is_read_only(self):
        with patch.object(TOOLS, "_invoke", return_value={"ok": True, "data": {}}) as invoke:
            self.assertIn("weave", TOOLS.slash_command(""))
            self.assertTrue(json.loads(TOOLS.slash_command("status"))["ok"])
            self.assertIn("Unsupported", TOOLS.slash_command("sync"))
            self.assertEqual(invoke.call_count, 1)

    def test_cli_command_forwards_only_arguments(self):
        p = argparse.ArgumentParser()
        TOOLS.setup_cli_parser(p)
        parsed = p.parse_args(["apply", "macbook", "demo", "--as", "demo-new"])
        with patch.object(TOOLS, "_invoke", return_value={"ok": True, "output": "done"}) as invoke:
            TOOLS.cli_command(parsed)
        self.assertEqual(
            invoke.call_args.args[0], ["apply", "macbook", "demo", "--as", "demo-new"]
        )

    def test_repo_metadata_and_bundled_skill(self):
        manifest = (ROOT / "plugin.yaml").read_text()
        self.assertIn("name: hermes-weave", manifest)
        self.assertIn("weave_apply", manifest)
        skill = (ROOT / "skills" / "hermes-weave" / "SKILL.md").read_text()
        self.assertTrue(skill.startswith("---\nname: hermes-weave\n"))
        self.assertIn("weave_status", skill)
        self.assertIn("weave_apply", skill)


if __name__ == "__main__":
    unittest.main()
