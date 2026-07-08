import json
import shlex
import sys
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "code"))

from mcp.setup import (  # noqa: E402
    CODEX_MCP_ADD_PREFIX,
    CLAUDE_MCP_ADD_PREFIX,
    OPENCODE_MCP_ADD_PREFIX,
    TRACE_MCP_MODULE,
    TRACE_MCP_SERVER_NAME,
    TRACE_MCP_TOOL,
    McpSetup,
)


def _seed_codex(home: Path, workspace: Path, old_workspace: Path) -> None:
    codex = home / ".codex"
    codex.mkdir(parents=True, exist_ok=True)
    (codex / "config.toml").write_text(
        textwrap.dedent(
            f"""
            model = "gpt-5"

            [mcp_servers.{TRACE_MCP_SERVER_NAME}]
            command = "/Applications/Trace.app/Contents/MacOS/python"
            args = ["-m", "{TRACE_MCP_MODULE}", "--workspace", "{old_workspace}"]

            [mcp_servers.{TRACE_MCP_SERVER_NAME}.env]
            PYTHONPATH = "/old/pythonpath"

            [mcp_servers.node_repl]
            command = "node_repl"
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    (codex / "hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Edit",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": (
                                        f"PYTHONPATH=/old python -m hooks.trace_codex_hook "
                                        f"--workspace {old_workspace} --phase pre"
                                    ),
                                }
                            ],
                        }
                    ],
                    "PostToolUse": [
                        {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo keep-me"}]}
                    ],
                }
            }
        ),
        encoding="utf-8",
    )


class CodexInstallTests(unittest.TestCase):
    def test_codex_install_replaces_stale_config_and_writes_hooks(self):
        import tempfile

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            home = Path(td).resolve() /"home"
            workspace = Path(td).resolve() /"ws"
            old_workspace = Path(td).resolve() /"old-ws"
            workspace.mkdir(parents=True)
            old_workspace.mkdir()
            _seed_codex(home, workspace, old_workspace)

            result = McpSetup(workspace=workspace, home=home).install("codex")
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["server_id"], "codex")
            self.assertTrue(result["restart_required"])
            self.assertTrue(result["config_path"].endswith("config.toml"))
            self.assertTrue(result["hook_path"].endswith("hooks.json"))

            toml = (home / ".codex" / "config.toml").read_text(encoding="utf-8")
            self.assertEqual(toml.count("[mcp_servers.trace]"), 1)
            self.assertEqual(toml.count("[mcp_servers.trace.env]"), 1)
            self.assertIn(TRACE_MCP_MODULE, toml)
            self.assertIn(str(workspace), toml)
            self.assertNotIn(str(old_workspace), toml)
            self.assertIn("[mcp_servers.node_repl]", toml)  # unrelated section preserved

            hooks = json.loads((home / ".codex" / "hooks.json").read_text(encoding="utf-8"))
            serialized = json.dumps(hooks)
            self.assertIn(str(workspace), serialized)
            self.assertNotIn(str(old_workspace), serialized)
            self.assertIn("echo keep-me", serialized)  # other PostToolUse entry preserved
            pre_matchers = [e.get("matcher") for e in hooks["hooks"]["PreToolUse"]]
            post_matchers = [e.get("matcher") for e in hooks["hooks"]["PostToolUse"]]
            self.assertIn("apply_patch|Edit|Write|MultiEdit", pre_matchers)
            self.assertIn("Bash|Shell|exec_command|apply_patch|Edit|Write|MultiEdit", post_matchers)

    def test_codex_install_is_idempotent_when_already_installed(self):
        import tempfile

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            home = Path(td).resolve() /"home"
            workspace = Path(td).resolve() /"ws"
            workspace.mkdir(parents=True)
            setup = McpSetup(workspace=workspace, home=home)

            first = setup.install("codex")
            self.assertTrue(first["ok"])
            second = setup.install("codex")
            self.assertTrue(second["ok"])
            self.assertTrue(second["already_installed"])

    def test_codex_row_reports_partial_when_only_mcp_present(self):
        import tempfile

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            home = Path(td).resolve() /"home"
            workspace = Path(td).resolve() /"ws"
            workspace.mkdir(parents=True)
            (home / ".codex").mkdir(parents=True)
            # Only TOML exists, no hooks.json -> partial.
            setup = McpSetup(workspace=workspace, home=home)
            setup._install_codex_mcp_config()

            rows = {r["id"]: r for r in setup.list_rows()}
            self.assertEqual(rows["codex"]["status"], "partial")
            self.assertEqual(rows["codex"]["status_label"], "待修复")


class OpenCodeInstallTests(unittest.TestCase):
    def test_opencode_install_writes_jsonc_config(self):
        import tempfile

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            home = Path(td).resolve() /"home"
            workspace = Path(td).resolve() /"ws"
            workspace.mkdir(parents=True)
            result = McpSetup(workspace=workspace, home=home).install("opencode")
            self.assertTrue(result["ok"])
            self.assertEqual(result["server_id"], "opencode")
            self.assertTrue(result["restart_required"])
            self.assertTrue(result["config_path"].endswith("opencode.jsonc"))

            config_path = home / ".config" / "opencode" / "opencode.jsonc"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            trace = config["mcp"][TRACE_MCP_SERVER_NAME]
            self.assertEqual(trace["enabled"], True)
            self.assertEqual(trace["type"], "local")
            self.assertEqual(trace["command"][0], sys.executable)
            self.assertIn("--workspace", trace["command"])
            self.assertIn(str(workspace.resolve()), trace["command"])
            self.assertIn("PYTHONPATH", trace["environment"])

    def test_opencode_install_preserves_existing_keys(self):
        import tempfile

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            home = Path(td).resolve() /"home"
            workspace = Path(td).resolve() /"ws"
            workspace.mkdir(parents=True)
            cfg = home / ".config" / "opencode" / "opencode.jsonc"
            cfg.parent.mkdir(parents=True)
            cfg.write_text(json.dumps({"mcp": {"other": {"type": "local"}}, "theme": "dark"}), encoding="utf-8")

            result = McpSetup(workspace=workspace, home=home).install("opencode")
            self.assertTrue(result["ok"])
            config = json.loads(cfg.read_text(encoding="utf-8"))
            self.assertIn("other", config["mcp"])  # preserved
            self.assertIn(TRACE_MCP_SERVER_NAME, config["mcp"])
            self.assertEqual(config["theme"], "dark")  # preserved


class ClaudeInstallTests(unittest.TestCase):
    def test_claude_install_already_installed_skips_subprocess(self):
        import tempfile

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            home = Path(td).resolve() /"home"
            workspace = Path(td).resolve() /"ws"
            workspace.mkdir(parents=True)
            # Pre-seed ~/.claude.json so inspection returns installed=True.
            (home).mkdir(parents=True, exist_ok=True)
            spec = McpSetup(workspace=workspace, home=home)
            launch = spec._launch_spec()
            user_config = home / ".claude.json"
            user_config.write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            TRACE_MCP_SERVER_NAME: {
                                "type": "stdio",
                                "command": launch["command"],
                                "args": launch["args"],
                                "env": launch["env"],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            called = {"count": 0}

            def _boom(*_a, **_kw):
                called["count"] += 1
                return {"ok": True}

            with patch.object(McpSetup, "_run_install_command", side_effect=_boom):
                result = McpSetup(workspace=workspace, home=home).install("claude")

            self.assertTrue(result["ok"])
            self.assertTrue(result["already_installed"])
            self.assertEqual(called["count"], 0)  # subprocess never invoked

    def test_claude_install_invokes_claude_binary(self):
        import tempfile

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            home = Path(td).resolve() /"home"
            workspace = Path(td).resolve() /"ws"
            workspace.mkdir(parents=True)

            captured = {}

            def _capture(binary, args):
                captured["binary"] = binary
                captured["args"] = list(args)
                return {"ok": True, "stdout": "", "stderr": ""}

            with patch.object(McpSetup, "_run_install_command", side_effect=_capture):
                result = McpSetup(workspace=workspace, home=home).install("claude")

            self.assertTrue(result["ok"], result)
            self.assertEqual(result["server_id"], "claude")
            self.assertTrue(result["restart_required"])
            self.assertTrue(result["approval_required"])  # claude needs the user to approve once
            self.assertEqual(captured["args"][0], "mcp")
            self.assertEqual(captured["args"][1], "add")
            self.assertIn("--scope", captured["args"])
            self.assertIn("user", captured["args"])
            self.assertIn(TRACE_MCP_SERVER_NAME, captured["args"])
            self.assertIn("--workspace", captured["args"])


class OtherAgentTests(unittest.TestCase):
    def test_other_server_id_returns_error(self):
        import tempfile

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            home = Path(td).resolve() /"home"
            workspace = Path(td).resolve() /"ws"
            workspace.mkdir(parents=True)
            result = McpSetup(workspace=workspace, home=home).install("other")
            self.assertFalse(result["ok"])
            self.assertIn("error", result)

    def test_unknown_server_id_returns_error(self):
        import tempfile

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            workspace = Path(td).resolve() /"ws"
            workspace.mkdir(parents=True)
            result = McpSetup(workspace=workspace, home=Path(td).resolve() /"home").install("not-a-real-agent")
            self.assertFalse(result["ok"])


class ListRowsTests(unittest.TestCase):
    def test_list_rows_returns_four_agents_in_order(self):
        import tempfile

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            workspace = Path(td).resolve() /"ws"
            workspace.mkdir(parents=True)
            rows = McpSetup(workspace=workspace, home=Path(td).resolve() /"home").list_rows()
            ids = [r["id"] for r in rows]
            self.assertEqual(ids, ["codex", "claude", "opencode", "other"])
            for row in rows:
                self.assertEqual(row["tool"], TRACE_MCP_TOOL)
                self.assertTrue(row["name"])
                self.assertTrue(row["command"])
                self.assertTrue(row["description"])
                self.assertIn(row["status"], {"installed", "partial", "not-installed", "manual"})
            self.assertFalse(rows[-1]["can_auto_install"])  # "other"
            self.assertEqual(rows[0]["command_prefix"], CODEX_MCP_ADD_PREFIX)
            self.assertEqual(rows[1]["command_prefix"], CLAUDE_MCP_ADD_PREFIX)
            self.assertEqual(rows[2]["command_prefix"], OPENCODE_MCP_ADD_PREFIX)

    def test_list_rows_other_row_includes_workspace_command(self):
        import tempfile

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            workspace = Path(td).resolve() /"ws"
            workspace.mkdir(parents=True)
            rows = McpSetup(workspace=workspace, home=Path(td).resolve() /"home").list_rows()
            other = rows[-1]
            self.assertIn(TRACE_MCP_MODULE, other["command"])
            self.assertIn(str(workspace), other["command"])


class CommandLineTests(unittest.TestCase):
    def test_command_line_shell_quotes_paths_with_spaces(self):
        from mcp.setup import _command_line

        line = _command_line(["python", "/path with spaces/foo.py", "--workspace", "/Users/me/my stuff"])
        # Only the two space-containing tokens should be quoted.
        self.assertIn("'/path with spaces/foo.py'", line)
        self.assertIn("'/Users/me/my stuff'", line)
        self.assertNotIn("/path with spaces/foo.py ", line)  # no un-quoted variant followed by space


if __name__ == "__main__":
    unittest.main()
