const commits = [
  {
    id: 4,
    time: "2026-05-30T16:58:12",
    author_agent: "claude",
    confidence: 0.92,
    summary: "3 个变化 by Claude Code",
  },
  {
    id: 3,
    time: "2026-05-30T16:52:41",
    author_agent: "codex",
    confidence: 0.88,
    summary: "2 个变化 by Codex CLI",
  },
  {
    id: 2,
    time: "2026-05-30T16:40:03",
    author_agent: "unknown",
    detection_method: "global_cli_fallback",
    confidence: 0.35,
    candidates: ["claude", "codex"],
    summary: "1 个变化 by unknown",
  },
];

const manifests = {
  4: [
    { file_path: "docs/notes.md", blob_hash: "new-notes" },
    { file_path: "src/app.py", blob_hash: "app-py" },
  ],
  3: [
    { file_path: "docs/notes.md", blob_hash: "old-notes" },
    { file_path: "src/app.py", blob_hash: "app-py" },
  ],
  2: [{ file_path: "docs/notes.md", blob_hash: "older-notes" }],
};

const blobs = {
  "older-notes": "# Demo Notes\n\nTrace tracks local edits.\n",
  "old-notes": "# Demo Notes\n\nTrace tracks local edits.\n\n- Workspace picker\n",
  "new-notes":
    "# Demo Notes\n\nTrace tracks local edits.\n\n- Workspace picker\n- Electron console\n",
  "app-py": 'print("trace")\n',
};

const demoWorkspace = "/Users/example/Trace/demo-workspace";

const mcpServers = [
  {
    id: "codex",
    name: "Codex",
    tool: "trace_record_files",
    installed: false,
    status: "not-installed",
    status_label: "可一键添加",
    canAutoInstall: true,
    action_label: "一键添加",
    command:
      "codex mcp add trace --env PYTHONPATH=/Users/example/final_project/code -- uv run python -m mcp.trace_server --workspace /Users/example/Trace/demo-workspace",
    config_path: "/Users/example/.codex/config.toml",
    hook_path: "/Users/example/.codex/hooks.json",
    description:
      "点击后写入 Codex MCP 与 hooks 配置；重启 Codex 后在 /hooks 信任一次即可生效。",
  },
  {
    id: "opencode",
    name: "OpenCode",
    tool: "trace_record_files",
    installed: false,
    status: "not-installed",
    status_label: "可一键添加",
    canAutoInstall: true,
    action_label: "一键添加",
    command:
      "opencode mcp add\n{\"mcp\":{\"trace\":{\"type\":\"local\",\"command\":[\"uv\",\"run\",\"python\",\"-m\",\"mcp.trace_server\",\"--workspace\",\"/Users/example/Trace/demo-workspace\"],\"enabled\":true,\"environment\":{\"PYTHONPATH\":\"/Users/example/final_project/code\"}}}}",
    config_path: "/Users/example/.config/opencode/opencode.jsonc",
    description:
      "点击后写入 ~/.config/opencode/opencode.jsonc，重启 OpenCode 后生效。",
  },
  {
    id: "claude",
    name: "Claude Code",
    tool: "trace_record_files",
    installed: false,
    status: "not-installed",
    status_label: "可一键添加",
    canAutoInstall: true,
    action_label: "一键添加",
    command:
      "claude mcp add --scope user trace -e PYTHONPATH=/Users/example/final_project/code -- uv run python -m mcp.trace_server --workspace /Users/example/Trace/demo-workspace",
    config_path: "/Users/example/Trace/demo-workspace/.mcp.json",
    description:
      "点击后调用 claude mcp add 写入用户级 Trace MCP；重启 Claude 后批准一次即可生效。",
  },
  {
    id: "other",
    name: "Other Agents",
    tool: "trace_record_files",
    installed: false,
    status: "manual",
    status_label: "复制配置",
    canAutoInstall: false,
    action_label: "复制配置",
    command:
      "PYTHONPATH=/Users/example/final_project/code\nuv run python -m mcp.trace_server --workspace /Users/example/Trace/demo-workspace",
    config_path: "",
    description:
      "其他的 agent 请复制到配置文件；支持 MCP stdio 的 agent 可使用这条 Trace server 命令。",
  },
];

export const mockApi = {
  async listCommits() {
    return commits;
  },

  async getManifest(commitId) {
    return manifests[commitId] || [];
  },

  async getPrevCommitId(commitId) {
    const previous = commits.find((commit) => commit.id < commitId);
    return previous ? previous.id : null;
  },

  async renderDiff(_filePath, prevHash, curHash) {
    const oldLines = (blobs[prevHash] || "").split("\n");
    const newLines = (blobs[curHash] || "").split("\n");
    return {
      ok: true,
      lines: newLines.map((line, index) => ({
        tag: oldLines[index] === line ? "normal" : "added",
        text: line,
      })),
    };
  },

  async renderDiffs(files) {
    const rendered = {};
    for (const file of files) {
      rendered[file.file_path] = await this.renderDiff(
        file.file_path,
        file.prev_hash,
        file.cur_hash,
      );
    }
    return { ok: true, files: rendered };
  },

  async restoreFile(commitId, filePath) {
    return {
      ok: true,
      commit_id: commitId,
      file_path: filePath,
      backup_id: null,
      test: true,
    };
  },

  async getWorkspace() {
    return demoWorkspace;
  },

  async listAgents() {
    return [
      {
        name: "claude",
        category: "cli",
        display_name: "Claude Code",
        color: "#D97757",
        commit_count: 12,
        last_time: "2026-05-30T16:58:12",
      },
      {
        name: "codex",
        category: "cli",
        display_name: "Codex CLI",
        color: "#10A37F",
        commit_count: 8,
        last_time: "2026-05-30T16:52:41",
      },
      {
        name: "openclaw",
        category: "cli",
        display_name: "OpenClaw",
        color: "#5E6AD2",
        commit_count: 0,
        last_time: null,
      },
      {
        name: "opencode",
        category: "cli",
        display_name: "OpenCode",
        color: "#2F80ED",
        commit_count: 0,
        last_time: null,
      },
      {
        name: "hermes",
        category: "cli",
        display_name: "Hermes",
        color: "#C89211",
        commit_count: 0,
        last_time: null,
      },
      {
        name: "kimi",
        category: "cli",
        display_name: "Kimi Code",
        color: "#8B5CF6",
        commit_count: 0,
        last_time: null,
      },
      {
        name: "human",
        category: "manual",
        display_name: "Human",
        color: "#cccccc",
        commit_count: 4,
        last_time: "2026-05-30T16:40:03",
      },
    ];
  },

  async getWorkspaceSummary() {
    return {
      workspace: demoWorkspace,
      db_path: `${demoWorkspace}/.trace/trace.db`,
      commit_count: 24,
      snapshot_count: 96,
      agent_count: 7,
    };
  },

  async listMcpSetup() {
    return mcpServers;
  },

  async installMcpServer(serverId) {
    return {
      ok: true,
      server_id: serverId,
      test: true,
      command: mcpServers.find((server) => server.id === serverId)?.command,
      hook_path: "/Users/example/.codex/hooks.json",
    };
  },

  async openGithub() {
    return {
      ok: true,
      url: "https://github.com/BUKOWSKIREAL/trace",
      test: true,
    };
  },
};
