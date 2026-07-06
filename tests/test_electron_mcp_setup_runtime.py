import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from tests._ci_platform import path_in_text


ROOT = Path(__file__).parent.parent


def run_node(script: str, *, env: dict[str, str] | None = None) -> dict:
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env={**os.environ, **(env or {})},
        check=True,
    )
    return json.loads(completed.stdout)


MOCK_ELECTRON = """
const Module = require('module');
const originalLoad = Module._load;
Module._load = function(request, parent, isMain) {
  if (request === 'electron') {
    return {
      app: { whenReady: () => ({ then: () => ({ catch: () => {} }) }), on: () => {}, exit: () => {} },
      BrowserWindow: function() {},
      ipcMain: { handle: () => {} },
      shell: { openExternal: async () => {} },
      dialog: { showErrorBox: () => {} },
    };
  }
  if (request === 'sqlite3') {
    return { Database: function() {} };
  }
  return originalLoad(request, parent, isMain);
};
"""


class TestElectronMcpSetupRuntime(unittest.TestCase):
    def test_codex_installer_replaces_stale_trace_config_and_hooks(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            workspace = Path(td) / "workspace with spaces"
            old_workspace = Path(td) / "old-workspace"
            workspace.mkdir(parents=True)
            old_workspace.mkdir()
            codex_dir = home / ".codex"
            codex_dir.mkdir(parents=True)
            (codex_dir / "config.toml").write_text(
                textwrap.dedent(
                    f"""
                    model = "gpt-5"

                    [mcp_servers.trace]
                    command = "/Applications/Trace.app/Contents/MacOS/python"
                    args = ["-m", "mcp.trace_server", "--workspace", "{old_workspace}"]

                    [mcp_servers.trace.env]
                    PYTHONPATH = "/old/pythonpath"

                    [mcp_servers.node_repl]
                    command = "node_repl"
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            (codex_dir / "hooks.json").write_text(
                json.dumps(
                    {
                        "hooks": {
                            "PreToolUse": [
                                {
                                    "matcher": "Edit",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": f"PYTHONPATH=/old python -m hooks.trace_codex_hook --workspace {old_workspace} --phase pre",
                                        }
                                    ],
                                }
                            ],
                            "PostToolUse": [
                                {
                                    "matcher": "Bash",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": "echo keep-me",
                                        }
                                    ],
                                }
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )

            script = MOCK_ELECTRON + f"""
process.env.TRACE_ELECTRON_MAIN_TEST = '1';
process.env.HOME = {json.dumps(str(home))};
process.env.TRACE_PROJECT_ROOT = {json.dumps(str(ROOT))};
process.argv = ['node', 'main.js', '--workspace', {json.dumps(str(workspace))}];
const main = require('./electron_app/main.js')._test;
const mcp = main.installCodexTraceMcpConfig();
const hook = main.installCodexTraceHookConfig();
const fs = require('fs');
const config = fs.readFileSync({json.dumps(str(codex_dir / "config.toml"))}, 'utf-8');
const hooks = JSON.parse(fs.readFileSync({json.dumps(str(codex_dir / "hooks.json"))}, 'utf-8'));
console.log(JSON.stringify({{
  mcp,
  hook,
  config,
  hooks,
  traceSectionCount: (config.match(/\\[mcp_servers\\.trace\\]/g) || []).length,
  traceEnvCount: (config.match(/\\[mcp_servers\\.trace\\.env\\]/g) || []).length,
}}));
"""
            result = run_node(script)

        self.assertTrue(result["mcp"]["installed"])
        self.assertTrue(result["hook"]["installed"])
        self.assertEqual(result["traceSectionCount"], 1)
        self.assertEqual(result["traceEnvCount"], 1)
        self.assertTrue(path_in_text(result["config"], workspace))
        self.assertFalse(path_in_text(result["config"], old_workspace))
        self.assertIn("mcp.trace_server", result["config"])
        self.assertIn("[mcp_servers.node_repl]", result["config"])
        serialized_hooks = json.dumps(result["hooks"])
        self.assertTrue(path_in_text(serialized_hooks, workspace))
        self.assertFalse(path_in_text(serialized_hooks, old_workspace))
        self.assertIn("echo keep-me", serialized_hooks)

    def test_windows_console_finds_packaged_trace_bridge_for_mcp_and_hooks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "Trace Portable"
            electron_dir = root / "electron"
            resources = electron_dir / "resources"
            resources.mkdir(parents=True)
            bridge = root / "TraceBridge.exe"
            console = electron_dir / "Trace Console.exe"
            bridge.write_text("", encoding="utf-8")
            console.write_text("", encoding="utf-8")
            workspace = Path(td) / "workspace with spaces"
            workspace.mkdir()

            script = MOCK_ELECTRON + f"""
Object.defineProperty(process, 'platform', {{ value: 'win32' }});
Object.defineProperty(process, 'resourcesPath', {{ value: {json.dumps(str(resources))} }});
Object.defineProperty(process, 'execPath', {{ value: {json.dumps(str(console))} }});
process.env.TRACE_ELECTRON_MAIN_TEST = '1';
process.argv = ['node', 'main.js', '--workspace', {json.dumps(str(workspace))}];
const main = require('./electron_app/main.js')._test;
const mcp = main.traceMcpLaunchSpec();
const hook = main.traceCodexHookLaunchSpec('pre');
const rows = main.mcpSetupRows();
console.log(JSON.stringify({{
  mcp,
  hook,
  rows,
  hookCommand: main.hookCommand('pre'),
  commandLine: main.commandLine([mcp.command, ...mcp.args]),
}}));
"""
            result = run_node(script)

        self.assertEqual(Path(result["mcp"]["command"]).name, "TraceBridge.exe")
        self.assertEqual(result["mcp"]["args"][0], "mcp.trace_server")
        self.assertIn(str(workspace), result["mcp"]["args"])
        self.assertEqual(result["mcp"]["env"], {})
        self.assertEqual(Path(result["hook"]["command"]).name, "TraceBridge.exe")
        self.assertEqual(result["hook"]["args"][0], "hooks.trace_codex_hook")
        self.assertNotIn("PYTHONPATH=", result["hookCommand"])
        serialized_rows = json.dumps(result["rows"])
        self.assertNotIn("undefined", serialized_rows)
        self.assertNotIn("PYTHONPATH=undefined", serialized_rows)
        self.assertIn("TraceBridge.exe", result["commandLine"])
        self.assertIn("Trace Portable", result["commandLine"])
        self.assertIn("workspace with spaces", result["commandLine"])

    def test_macos_bundled_mcp_disables_bytecode_writes(self):
        with tempfile.TemporaryDirectory() as td:
            outer = Path(td) / "Trace.app"
            electron_resources = (
                outer
                / "Contents"
                / "Resources"
                / "electron"
                / "Trace Console.app"
                / "Contents"
                / "Resources"
            )
            python = outer / "Contents" / "MacOS" / "python"
            python_lib = outer / "Contents" / "Resources" / "lib" / "python3.13"
            workspace = Path(td) / "workspace"
            electron_resources.mkdir(parents=True)
            python.parent.mkdir(parents=True)
            python.write_text("", encoding="utf-8")
            python_lib.mkdir(parents=True)
            workspace.mkdir()

            script = MOCK_ELECTRON + f"""
Object.defineProperty(process, 'platform', {{ value: 'darwin' }});
Object.defineProperty(process, 'resourcesPath', {{ value: {json.dumps(str(electron_resources))} }});
process.env.TRACE_ELECTRON_MAIN_TEST = '1';
process.argv = ['node', 'main.js', '--workspace', {json.dumps(str(workspace))}];
const main = require('./electron_app/main.js')._test;
const mcp = main.traceMcpLaunchSpec();
const hook = main.traceCodexHookLaunchSpec('pre');
console.log(JSON.stringify({{ mcp, hook, hookCommand: main.hookCommand('pre') }}));
"""
            result = run_node(script)

        self.assertEqual(Path(result["mcp"]["command"]), python)
        self.assertEqual(result["mcp"]["env"]["PYTHONDONTWRITEBYTECODE"], "1")
        self.assertEqual(result["hook"]["env"]["PYTHONDONTWRITEBYTECODE"], "1")
        self.assertIn("PYTHONDONTWRITEBYTECODE=", result["hookCommand"])
        self.assertIn(str(python_lib), result["mcp"]["env"]["PYTHONPATH"])

    def test_windows_window_options_do_not_use_transparent_macos_titlebar(self):
        script = MOCK_ELECTRON + f"""
Object.defineProperty(process, 'platform', {{ value: 'win32' }});
process.env.TRACE_ELECTRON_MAIN_TEST = '1';
process.env.TRACE_PROJECT_ROOT = {json.dumps(str(ROOT))};
process.argv = ['node', 'main.js', '--workspace', {json.dumps(str(ROOT / "test_workspace"))}];
const main = require('./electron_app/main.js')._test;
console.log(JSON.stringify(main.createWindowOptions()));
"""
        result = run_node(script)

        self.assertEqual(result["backgroundColor"], "#0a0a0a")
        self.assertNotIn("transparent", result)
        self.assertNotIn("titleBarStyle", result)
        self.assertNotIn("vibrancy", result)
        self.assertNotIn("visualEffectState", result)


if __name__ == "__main__":
    unittest.main()
