"""
Electron renderer 交互契约测试。

锁定顶部导航和 hero chips 的最小行为：这些控件不能只是静态文本，
必须有可绑定的 data-* 契约，并且 main/preload 提供对应 IPC。
"""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
ELECTRON = ROOT / "electron_app"


class TestElectronRendererInteractions(unittest.TestCase):
    def _read(self, relative: str) -> str:
        return (ELECTRON / relative).read_text(encoding="utf-8")

    def _package_json(self) -> dict:
        return json.loads(self._read("package.json"))

    def test_renderer_is_vue_vite_app(self):
        package = self._package_json()
        scripts = package["scripts"]
        self.assertEqual(scripts["dev:renderer"], "vite --host 127.0.0.1")
        self.assertEqual(scripts["build:renderer"], "vite build")
        self.assertEqual(scripts["start"], "npm run build:renderer && electron .")
        self.assertEqual(
            scripts["build:win"],
            "npm run build:renderer && electron-builder --win --x64",
        )
        self.assertIn("vue", package["dependencies"])
        self.assertIn("@vitejs/plugin-vue", package["devDependencies"])
        self.assertIn("vite", package["devDependencies"])

        self.assertTrue((ELECTRON / "vite.config.js").exists())
        self.assertTrue((ELECTRON / "src" / "App.vue").exists())
        self.assertTrue((ELECTRON / "src" / "main.js").exists())
        self.assertTrue((ELECTRON / "src" / "mockApi.js").exists())

    def test_electron_builder_uses_trace_app_icon(self):
        package = self._package_json()
        self.assertEqual(package["build"]["mac"]["icon"], "icon.png")
        self.assertIn("icon.png", package["build"]["files"])
        self.assertTrue((ELECTRON / "icon.png").exists())

    def test_nav_and_chips_have_action_contracts(self):
        html = self._read("src/App.vue")
        for view in ("commits", "agents", "workspace"):
            self.assertIn(f'data-view="{view}"', html)
        for action in ("show-diff", "open-github", "refresh"):
            self.assertIn(f'data-action="{action}"', html)
        self.assertIn('data-action="restore-file"', html)
        self.assertIn('id="commit-view"', html)
        self.assertIn('id="detail-view"', html)
        self.assertIn('id="status-line"', html)

    def test_renderer_binds_click_handlers_for_all_visible_controls(self):
        vue = self._read("src/App.vue")
        self.assertIn('@click="showCommits"', vue)
        self.assertIn('@click="showAgents"', vue)
        self.assertIn('@click="showWorkspace"', vue)
        self.assertIn('@click="showDiff"', vue)
        self.assertIn('@click="openGithub"', vue)
        self.assertIn('@click="manualRefresh"', vue)
        self.assertIn('@click="restoreFile', vue)
        self.assertIn("row.canRestore", vue)
        self.assertIn("回退", vue)
        self.assertIn("refresh", vue)
        self.assertNotIn('>刷新<', vue)
        for fn in (
            "showCommits",
            "showAgents",
            "showWorkspace",
            "showDiff",
            "openGithub",
            "manualRefresh",
            "restoreFile",
        ):
            self.assertIn(f"async function {fn}(", vue)

    def test_main_process_exposes_interactive_ipc(self):
        main_js = self._read("main.js")
        for channel in (
            "list-agents",
            "get-workspace-summary",
            "open-github",
            "restore-file",
        ):
            self.assertIn(f'ipcMain.handle("{channel}"', main_js)
        self.assertIn("shell.openExternal", main_js)
        self.assertIn("--renderer-smoke-test", main_js)
        self.assertIn("runRendererSmokeTest", main_js)
        self.assertIn("https://github.com/BUKOWSKIREAL/trace", main_js)
        self.assertIn("renderer-dist", main_js)
        self.assertIn("VITE_DEV_SERVER_URL", main_js)

    def test_window_options_keep_windows_console_draggable(self):
        main_js = self._read("main.js")
        css = self._read("src/style.css")
        self.assertIn("function createWindowOptions()", main_js)
        self.assertIn('if (process.platform === "darwin")', main_js)
        self.assertIn("return { ...baseOptions, ...macWindowOptions };", main_js)
        self.assertIn("return baseOptions;", main_js)
        self.assertIn("createWindowOptions()", main_js)
        self.assertIn("-webkit-app-region: drag;", css)
        self.assertIn("-webkit-app-region: no-drag;", css)
        self.assertNotIn("titleBarStyle: \"hiddenInset\", // macOS", main_js)

    def test_main_process_exposes_handler_backed_diff_ipc(self):
        main_js = self._read("main.js")
        self.assertIn('ipcMain.handle("render-diff"', main_js)
        self.assertIn('ipcMain.handle("render-diffs"', main_js)
        self.assertIn("core.electron_diff_bridge", main_js)
        self.assertIn("core.electron_restore_bridge", main_js)
        self.assertIn("TRACE_PYTHON_BRIDGE_MODE", main_js)
        self.assertIn("bridge-exe", main_js)
        self.assertIn("spawn(", main_js)

    def test_main_process_exposes_mcp_setup_ipc(self):
        main_js = self._read("main.js")
        self.assertIn('ipcMain.handle("list-mcp-setup"', main_js)
        self.assertIn('ipcMain.handle("install-mcp-server"', main_js)
        self.assertIn("TRACE_MCP_MODULE", main_js)
        self.assertIn("mcp.trace_server", main_js)
        self.assertIn("trace_record_files", main_js)
        self.assertIn("codex mcp add", main_js)
        self.assertIn("claude mcp add", main_js)
        self.assertIn("opencode mcp add", main_js)
        self.assertIn("environment", main_js)
        self.assertIn(".claude.json", main_js)
        self.assertIn("TRACE_CODEX_HOOK_MODULE", main_js)
        self.assertIn("hooks.trace_codex_hook", main_js)
        self.assertIn("hooks.json", main_js)
        self.assertIn("PreToolUse", main_js)
        self.assertIn("PostToolUse", main_js)

    def test_main_process_uses_persisted_workspace_when_no_cli_arg(self):
        main_js = self._read("main.js")
        self.assertIn("last_workspace", main_js)
        self.assertIn("Application Support", main_js)
        self.assertIn("state.json", main_js)
        self.assertNotIn("Desktop/study/python/final_project/test_workspace", main_js)

    def test_main_process_resolves_relative_workspace_before_bridge_payloads(self):
        main_js = self._read("main.js")
        self.assertIn("function normalizeWorkspace(value)", main_js)
        self.assertIn("return path.resolve(expandHome(value || userHome()))", main_js)
        self.assertIn('return normalizeWorkspace(arg.split("=")[1])', main_js)
        self.assertIn("workspace = parseWorkspace()", main_js)

    def test_main_process_notifies_renderer_when_workspace_changes(self):
        main_js = self._read("main.js")
        self.assertIn("watchWorkspaceState", main_js)
        self.assertIn("workspace-changed", main_js)
        self.assertIn('webContents.send("workspace-changed"', main_js)

    def test_main_process_smoke_covers_commit_version_graph(self):
        main_js = self._read("main.js")
        self.assertIn("document.querySelectorAll('.version-node').length > 0", main_js)
        self.assertIn(
            "document.querySelectorAll('.graph-connection').length > 0", main_js
        )
        self.assertIn("graphNodeSelectable", main_js)

    def test_preload_exposes_renderer_api(self):
        preload = self._read("preload.js")
        expected = {
            "listAgents": "list-agents",
            "getWorkspaceSummary": "get-workspace-summary",
            "openGithub": "open-github",
        }
        for api_name, channel in expected.items():
            self.assertIn(f'{api_name}: () => ipcRenderer.invoke("{channel}")', preload)
        self.assertIn(
            'ipcRenderer.invoke("render-diff", filePath, prevHash, curHash)', preload
        )
        self.assertIn(
            'renderDiffs: (files) => ipcRenderer.invoke("render-diffs", files)', preload
        )
        self.assertIn('ipcRenderer.invoke("restore-file", commitId, filePath)', preload)
        self.assertIn("onWorkspaceChanged", preload)
        self.assertIn("workspace-changed", preload)

    def test_preload_exposes_mcp_setup_api(self):
        preload = self._read("preload.js")
        self.assertIn('listMcpSetup: () => ipcRenderer.invoke("list-mcp-setup")', preload)
        self.assertIn(
            'installMcpServer: (serverId) => ipcRenderer.invoke("install-mcp-server", serverId)',
            preload,
        )

    def test_renderer_uses_handler_diff_ipc(self):
        vue = self._read("src/App.vue")
        css = self._read("src/style.css")
        self.assertIn("api.renderDiff(filePath, prev, cur)", vue)
        self.assertIn("api.renderDiffs", vue)
        self.assertIn("api.restoreFile(commitId, filePath)", vue)
        self.assertIn("restore-file", vue)
        self.assertIn("restoreButtonVisible", self._read("main.js"))
        self.assertIn(".diff-file-path", css)
        self.assertIn("text-overflow: ellipsis;", css)
        self.assertIn("flex: 0 0 auto;", css)
        self.assertNotIn("function ndiff", vue)
        self.assertNotIn("function isBinary", vue)
        self.assertNotIn("二进制文件，未做内容 diff", vue)

    def test_renderer_explains_duplicate_commit_snapshots(self):
        vue = self._read("src/App.vue")
        self.assertIn("快照完全一致", vue)

    def test_renderer_refreshes_when_workspace_changes(self):
        vue = self._read("src/App.vue")
        self.assertIn("api.onWorkspaceChanged", vue)
        self.assertIn("handleWorkspaceChanged", vue)
        self.assertIn("workspacePath.value = nextWorkspace", vue)

    def test_renderer_auto_selects_latest_commit_after_poll_refresh(self):
        vue = self._read("src/App.vue")
        self.assertIn(
            "async function refreshTimeline({ autoSelectLatest = false } = {})", vue
        )
        self.assertIn("const previousTopId = commits.value[0]?.id ?? null", vue)
        self.assertIn("selectedId === previousTopId", vue)
        self.assertIn("await onSelectCommit(latestId)", vue)
        self.assertIn("refreshTimeline({ autoSelectLatest: true })", vue)

    def test_renderer_has_manual_refresh_button(self):
        vue = self._read("src/App.vue")
        css = self._read("src/style.css")
        self.assertIn('data-action="refresh"', vue)
        self.assertIn('@click="manualRefresh"', vue)
        self.assertIn("async function manualRefresh()", vue)
        self.assertIn("refreshLoading.value = true", vue)
        self.assertIn('refreshLoading ? "refreshing" : "refresh"', vue)
        self.assertIn("refresh-button", css)

    def test_renderer_has_startup_mcp_setup_panel(self):
        vue = self._read("src/App.vue")
        css = self._read("src/style.css")
        mock_api = self._read("src/mockApi.js")
        for expected in (
            'data-view="mcp"',
            'data-action="install-mcp"',
            'data-action="copy-mcp-command"',
            "@click=\"showMcpSetup\"",
            "mcpNeedsSetup",
            "mcpServers",
            "installMcpServer",
            "copyMcpCommand",
            "trace_record_files",
            "hook_path",
            "/hooks",
            "[ MCP ]",
        ):
            self.assertIn(expected, vue)
        self.assertIn(".mcp-startup-tip", css)
        self.assertIn(".mcp-card", css)
        self.assertIn("listMcpSetup", mock_api)
        self.assertIn("installMcpServer", mock_api)
        self.assertIn("trace_record_files", mock_api)
        for expected in ("Claude Code", "OpenCode", "Other Agents"):
            self.assertIn(expected, mock_api)
            self.assertIn(expected, self._read("main.js"))

    def test_renderer_has_animated_commit_version_graph(self):
        vue = self._read("src/App.vue")
        css = self._read("src/style.css")
        self.assertIn("graphCommits", vue)
        self.assertIn("commit-version-graph", vue)
        self.assertIn('aria-label="commit 版本图"', vue)
        self.assertIn("graph-connection", vue)
        self.assertIn("version-node", vue)
        self.assertIn("version-node-pulse", vue)
        self.assertIn("--node-x", vue)
        self.assertIn("--node-y", vue)
        self.assertIn('@click="onSelectCommit(commit.id)"', vue)
        self.assertIn("@keyframes graph-line-flow", css)
        self.assertIn("@keyframes graph-node-pulse", css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", css)

    def test_renderer_hero_title_uses_times_new_roman(self):
        css = self._read("src/style.css")
        self.assertIn(".hero-title {", css)
        self.assertIn('font-family: "Times New Roman", Times, serif;', css)
        self.assertNotIn(':root[data-theme="light"] .hero-title', css)

    def test_renderer_supports_system_theme_option(self):
        vue = self._read("src/App.vue")
        self.assertIn("@click=\"setTheme('system')\"", vue)
        self.assertIn(":class=\"{ active: theme === 'system' }\"", vue)
        self.assertIn('const theme = ref("system")', vue)
        self.assertIn('window.matchMedia?.("(prefers-color-scheme: dark)")', vue)
        self.assertIn('systemThemeQuery?.addEventListener?.("change", applyTheme)', vue)
        self.assertIn(
            'systemThemeQuery?.removeEventListener?.("change", applyTheme)', vue
        )

    def test_main_process_expands_tilde_workspace(self):
        main_js = self._read("main.js")
        self.assertIn("function expandHome(input)", main_js)
        self.assertIn("ensureWorkspaceReady", main_js)
        self.assertIn("core.electron_init_bridge", main_js)
        self.assertIn("bundledTraceLayout", main_js)
        self.assertIn("resolvePythonBridgeCommand", main_js)

    def test_renderer_surfaces_ambiguous_agent_candidates(self):
        vue = self._read("src/App.vue")
        main_js = self._read("main.js")
        preload = self._read("preload.js")
        self.assertIn("agentLabel(commit)", vue)
        self.assertIn("candidatesOf(commit)", vue)
        self.assertIn("低置信度候选", vue)
        self.assertIn("reassignSelectedCommit", vue)
        self.assertIn("revertAgent", vue)
        self.assertIn("parseCandidates(row.candidates)", main_js)
        self.assertIn("detection_method, confidence, candidates", main_js)
        self.assertIn("reassign-commit", main_js)
        self.assertIn("revert-agent", main_js)
        self.assertIn("reassignCommit", preload)
        self.assertIn("revertAgent", preload)

    def test_renderer_mock_and_styles_include_opencode_hermes_and_kimi_agents(self):
        mock_api = self._read("src/mockApi.js")
        css = self._read("src/style.css")
        self.assertIn('name: "opencode"', mock_api)
        self.assertIn('display_name: "OpenCode"', mock_api)
        self.assertIn('name: "hermes"', mock_api)
        self.assertIn('display_name: "Hermes"', mock_api)
        self.assertIn('name: "kimi"', mock_api)
        self.assertIn('display_name: "Kimi Code"', mock_api)
        self.assertIn("agent_count: 7", mock_api)
        for agent in ("opencode", "hermes", "kimi"):
            self.assertIn(f".agent-card.{agent} .agent-name", css)
            self.assertIn(f".tr-agent.{agent}", css)

    def test_agents_panel_filters_noisy_gui_and_script_sources(self):
        vue = self._read("src/App.vue")
        self.assertIn("HIDDEN_AGENT_NAMES", vue)
        for hidden_name in ("cursor", "vscode", "local-script", "claude-script", "codex-script"):
            self.assertIn(f'"{hidden_name}"', vue)
        self.assertIn("visibleAgents", vue)
        self.assertIn('v-for="agent in visibleAgents"', vue)
        self.assertIn("visibleAgents.length", vue)
        self.assertIn("visibleAgents.value.reduce", vue)
        self.assertIn("visibleAgents.value.filter", vue)

    def test_agents_panel_layout_guards_against_card_overlap(self):
        css = self._read("src/style.css")
        self.assertIn(
            "grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));", css
        )
        self.assertIn(".agent-card {", css)
        self.assertIn("min-height: 150px;", css)
        self.assertIn("overflow: hidden;", css)
        self.assertIn("overflow-wrap: anywhere;", css)
        self.assertIn("text-overflow: ellipsis;", css)
        self.assertIn(".agent-card .panel-meta {", css)

    def test_renderer_mock_data_does_not_embed_local_test_workspace(self):
        for relative in ("src/App.vue", "src/mockApi.js"):
            content = self._read(relative)
            self.assertNotIn(
                "Desktop/study/python/final_project/test_workspace", content
            )


if __name__ == "__main__":
    unittest.main()
