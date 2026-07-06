"""
DEMO 文档和打包脚本的回归测试。

这些测试锁定最终交付物的外层契约：演示文档走 uv 工作流，
Phase 5 打包不再标成待做，并且仓库提供 macOS .app/.dmg 构建脚本
和失败时可用的源码安装脚本。
"""
import ast
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parent.parent


class TestDemoDocument(unittest.TestCase):
    def test_demo_uses_uv_install_flow(self):
        text = (ROOT / "DEMO.md").read_text(encoding="utf-8")
        self.assertIn("uv sync", text)
        self.assertIn("uv run python code/main.py", text)
        self.assertNotIn("pip install -r requirements.txt", text)

    def test_demo_marks_packaging_as_deliverable(self):
        text = (ROOT / "DEMO.md").read_text(encoding="utf-8")
        self.assertIn("scripts/build_macos_app.sh", text)
        self.assertIn("install.sh", text)
        self.assertNotIn("Phase 5 待做", text)


class TestPackagingFiles(unittest.TestCase):
    def test_setup_py_declares_py2app_application(self):
        setup_py = ROOT / "setup.py"
        self.assertTrue(setup_py.exists())
        tree = ast.parse(setup_py.read_text(encoding="utf-8"))
        calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and getattr(node.func, "id", None) == "setup"
        ]
        self.assertEqual(len(calls), 1)
        keywords = {kw.arg: kw.value for kw in calls[0].keywords}
        self.assertEqual(ast.literal_eval(keywords["name"]), "Trace")
        self.assertIn("app", keywords)
        self.assertIn("options", keywords)
        self.assertEqual(
            ast.literal_eval(keywords["app"]),
            ["code/main.py"],
        )
        options = ast.literal_eval(keywords["options"])
        self.assertIn("py2app", options)
        self.assertIn("packages", options["py2app"])
        self.assertIn("mcp", options["py2app"]["packages"])
        self.assertIn("hooks", options["py2app"]["packages"])
        self.assertEqual(options["py2app"]["iconfile"], "assets/app_icon.icns")
        plist = options["py2app"]["plist"]
        self.assertEqual(plist["CFBundleName"], "Trace")
        self.assertEqual(plist["CFBundleDisplayName"], "Trace")
        self.assertTrue((ROOT / "assets" / "app_icon.icns").exists())
        self.assertTrue((ROOT / "assets" / "app_icon.png").exists())

    def test_build_script_and_install_fallback_exist(self):
        build_script = ROOT / "scripts" / "build_macos_app.sh"
        windows_script = ROOT / "scripts" / "build_windows_app.ps1"
        install_script = ROOT / "install.sh"
        self.assertTrue(build_script.exists())
        self.assertTrue(windows_script.exists())
        self.assertTrue(install_script.exists())
        build_text = build_script.read_text(encoding="utf-8")
        windows_text = windows_script.read_text(encoding="utf-8")
        install_text = install_script.read_text(encoding="utf-8")
        self.assertIn("npx electron-builder", build_text)
        self.assertIn("npm run build:renderer", build_text)
        self.assertIn("Contents/Resources/electron", build_text)
        self.assertIn("APP_NAME=\"Trace\"", build_text)
        self.assertIn("ELECTRON_APP_NAME=\"Trace Console\"", build_text)
        self.assertIn("uv run python setup.py py2app", build_text)
        self.assertIn("install_name_tool", build_text)
        self.assertIn("_sqlite3.so", build_text)
        self.assertIn("codesign --force --sign -", build_text)
        self.assertIn("codesign --verify --deep --strict", build_text)
        self.assertIn("create-dmg", build_text)
        self.assertIn("install.sh", build_text)
        self.assertIn("npx electron-builder --win --dir", windows_text)
        self.assertIn("uv run python -m PyInstaller", windows_text)
        self.assertIn("Trace-windows.spec", windows_text)
        self.assertIn("TRACE_ELECTRON_WIN_DIR", windows_text)
        self.assertIn("$ElectronOutName", windows_text)
        self.assertIn("Remove-Item $ExpectedElectronOutDir -Recurse -Force", windows_text)
        self.assertNotIn("Select-Object -First 1", windows_text)
        self.assertIn("Trace.exe", windows_text)
        self.assertIn("TraceBridge.exe", windows_text)
        self.assertIn("electron\\Trace Console.exe", windows_text)
        self.assertIn("mcp.trace_server", windows_text)
        self.assertIn("tools/list", windows_text)
        self.assertIn("Content-Length", windows_text)
        self.assertIn("StandardInput.BaseStream.Write", windows_text)
        self.assertIn("RedirectStandardInput", windows_text)
        self.assertNotIn("| & $BridgeExe", windows_text)
        self.assertIn("Copy-Item", windows_text)
        packaging_text = (ROOT / "PACKAGING.md").read_text(encoding="utf-8")
        self.assertIn("TraceBridge MCP", packaging_text)
        self.assertIn("uv sync", install_text)
        self.assertIn("code/main.py", install_text)
        self.assertIn("dist/Trace.command", install_text)

    def test_windows_bridge_handshake_checks_exit_before_dispose(self):
        windows_text = (ROOT / "scripts" / "build_windows_app.ps1").read_text(
            encoding="utf-8"
        )
        exit_check = windows_text.index("$BridgeExitCode = $BridgeProcess.ExitCode")
        cached_check = windows_text.index("$BridgeExitCode -ne 0")
        dispose = windows_text.index("$BridgeProcess.Dispose()")
        self.assertLess(exit_check, dispose)
        self.assertGreater(cached_check, dispose)

    def test_windows_ci_runs_full_packaging_script(self):
        workflow = (ROOT / ".github" / "workflows" / "build-windows.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("runs-on: windows-latest", workflow)
        self.assertIn("astral-sh/setup-uv", workflow)
        self.assertIn("actions/setup-python", workflow)
        self.assertIn('python-version: "3.13"', workflow)
        self.assertIn("actions/setup-node", workflow)
        self.assertIn("uv run python scripts/run_windows_ci_tests.py", workflow)
        self.assertIn("./scripts/build_windows_app.ps1", workflow)
        self.assertIn("path: dist/Trace", workflow)
        self.assertIn("if-no-files-found: error", workflow)

    def test_windows_pyinstaller_spec_exists(self):
        spec = ROOT / "Trace-windows.spec"
        bridge = ROOT / "code" / "electron_bridge.py"
        mcp_server = ROOT / "code" / "mcp" / "trace_server.py"
        self.assertTrue(spec.exists())
        self.assertTrue(bridge.exists())
        self.assertTrue(mcp_server.exists())
        text = spec.read_text(encoding="utf-8")
        self.assertIn("main.py", text)
        self.assertIn("electron_bridge.py", text)
        self.assertIn("name=\"Trace\"", text)
        self.assertIn("name=\"TraceBridge\"", text)
        self.assertIn("Trace Console.exe", text)
        self.assertIn("missing Electron console executable", text)
        self.assertIn("TRACE_ELECTRON_WIN_DIR", text)
        self.assertIn("menubar.tray_pystray", text)
        self.assertIn("core.electron_diff_bridge", text)
        self.assertIn("core.electron_restore_bridge", text)
        self.assertIn("hooks.trace_codex_hook", text)
        self.assertIn('"mcp.trace_server"', text)
        self.assertIn('"daemon.trace_activity"', text)
        bridge_text = bridge.read_text(encoding="utf-8")
        self.assertIn("mcp.trace_server", bridge_text)
        self.assertIn("hooks.trace_codex_hook", bridge_text)

    def test_readme_documents_trace_mcp_server(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("[mcp_servers.trace]", text)
        self.assertIn("mcp.trace_server", text)
        self.assertIn("hooks.trace_codex_hook", text)
        self.assertIn("PYTHONPATH", text)
        self.assertIn("trace_record_files", text)
        self.assertIn(".trace/trace_activity.jsonl", text)

    def test_mcp_docs_do_not_publish_stale_setup_instructions(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        mcp_setup = (ROOT / "MCP_SETUP.md").read_text(encoding="utf-8")
        cursor_setup = (ROOT / "CURSOR_SETUP.md").read_text(encoding="utf-8")
        cursor_script = (ROOT / "scripts" / "setup_cursor_mcp.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('command = "/path/to/project/.venv/bin/python"', readme)
        self.assertIn('args = ["-m", "mcp.trace_server"', readme)
        self.assertIn("Cursor 配置", mcp_setup)
        self.assertIn("Codex CLI 配置", mcp_setup)
        self.assertNotIn("在 Cursor/Codex 中使用", mcp_setup)
        self.assertIn('"command": "py"', cursor_setup)
        self.assertIn("默认: 项目根目录", cursor_script)
        self.assertNotIn("默认: 项目根目录/test_workspace", cursor_script)

    def test_project_mcp_file_does_not_override_packaged_trace_server(self):
        project_mcp = ROOT / ".mcp.json"
        if not project_mcp.exists():
            return

        config = json.loads(project_mcp.read_text(encoding="utf-8"))
        self.assertNotIn("trace", config.get("mcpServers", {}))

    def test_pyproject_has_packaging_dependencies(self):
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("py2app", text)
        self.assertIn("pyinstaller", text)
