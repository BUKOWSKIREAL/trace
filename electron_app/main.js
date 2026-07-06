// Electron 主进程
// 负责：
// - 创建 BrowserWindow（macOS 使用沉浸标题栏，Windows/Linux 使用原生可拖动窗口）
// - 把 workspace path 用 query string 传给 renderer
// - 暴露 sqlite 查询接口给 renderer（通过 preload context bridge）

const { app, BrowserWindow, ipcMain, shell, dialog } = require("electron");
const { spawn } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");
const sqlite3 = require("sqlite3");

const GITHUB_URL = "https://github.com/BUKOWSKIREAL/trace";
const PYTHON_DIFF_MODULE = "core.electron_diff_bridge";
const PYTHON_RESTORE_MODULE = "core.electron_restore_bridge";
const PYTHON_REASSIGN_MODULE = "core.electron_reassign_bridge";
const PYTHON_REVERT_AGENT_MODULE = "core.electron_revert_agent_bridge";
const PYTHON_INIT_MODULE = "core.electron_init_bridge";
const TRACE_MCP_MODULE = "mcp.trace_server";
const TRACE_CODEX_HOOK_MODULE = "hooks.trace_codex_hook";
const TRACE_MCP_TOOL = "trace_record_files";
const TRACE_MCP_SERVER_NAME = "trace";
const CODEX_MCP_ADD_PREFIX = "codex mcp add";
const CLAUDE_MCP_ADD_PREFIX = "claude mcp add";
const OPENCODE_MCP_ADD_PREFIX = "opencode mcp add";
const IS_TEST_IMPORT = process.env.TRACE_ELECTRON_MAIN_TEST === "1";

function userHome() {
  return process.env.HOME || process.env.USERPROFILE || os.homedir();
}

function pathAppearsInText(text, targetPath) {
  const normalized = String(targetPath || "");
  if (!normalized) return false;
  const candidates = new Set([
    normalized,
    normalized.replace(/\\/g, "/"),
    normalized.replace(/\\/g, "\\\\"),
  ]);
  for (const candidate of candidates) {
    if (candidate && String(text).includes(candidate)) return true;
  }
  return false;
}

function stateFilePath() {
  if (process.platform === "darwin") {
    return path.join(
      userHome(),
      "Library",
      "Application Support",
      "Trace",
      "state.json",
    );
  }
  if (process.platform === "win32") {
    return path.join(process.env.APPDATA || userHome(), "Trace", "state.json");
  }
  return path.join(
    process.env.XDG_CONFIG_HOME || path.join(userHome(), ".config"),
    "trace",
    "state.json",
  );
}

function loadPersistedWorkspace() {
  try {
    const state = JSON.parse(fs.readFileSync(stateFilePath(), "utf-8"));
    if (state.last_workspace && fs.existsSync(state.last_workspace)) {
      return state.last_workspace;
    }
  } catch (_e) {
    // No persisted workspace yet; caller decides the fallback.
  }
  return null;
}

function expandHome(input) {
  const raw = String(input || "").trim();
  if (!raw) return userHome();
  if (raw === "~") return userHome();
  if (raw.startsWith("~/") || raw.startsWith("~\\")) {
    return path.join(userHome(), raw.slice(2));
  }
  return raw;
}

function normalizeWorkspace(value) {
  return path.resolve(expandHome(value || userHome()));
}

// 解析 workspace 参数：--workspace=/path/to/proj
function parseWorkspace() {
  for (const arg of process.argv) {
    if (arg.startsWith("--workspace="))
      return normalizeWorkspace(arg.split("=")[1]);
    if (arg === "--workspace") {
      const idx = process.argv.indexOf(arg);
      return normalizeWorkspace(process.argv[idx + 1]);
    }
  }
  return normalizeWorkspace(loadPersistedWorkspace() || userHome());
}

let workspace = parseWorkspace();
const rendererSmokeTest = process.argv.includes("--renderer-smoke-test");
const rendererDevServerUrl = process.env.VITE_DEV_SERVER_URL;
let workspaceWatcher = null;

function dbPath() {
  return path.join(workspace, ".trace", "trace.db");
}

function projectRoot() {
  if (process.env.TRACE_PROJECT_ROOT) return process.env.TRACE_PROJECT_ROOT;
  const windowsPortable = windowsPortableLayout();
  if (windowsPortable) return windowsPortable.appDir;
  const bundled = bundledTraceLayout();
  if (bundled) return bundled.traceResources;
  return path.resolve(__dirname, "..");
}

function windowsPortableLayout() {
  if (process.platform !== "win32") return null;
  const candidates = [];
  if (process.resourcesPath) {
    candidates.push(path.resolve(process.resourcesPath, "..", ".."));
  }
  if (process.execPath) {
    candidates.push(path.resolve(path.dirname(process.execPath), ".."));
  }
  for (const appDir of candidates) {
    const bridge = path.join(appDir, "TraceBridge.exe");
    const consoleExe = path.join(appDir, "electron", "Trace Console.exe");
    if (fs.existsSync(bridge) && fs.existsSync(consoleExe)) {
      return { appDir, bridge };
    }
  }
  return null;
}

function bundledTraceLayout() {
  if (process.platform !== "darwin" || !process.resourcesPath) return null;
  const traceResources = path.resolve(process.resourcesPath, "../../../..");
  const python = path.resolve(process.resourcesPath, "../../../../../MacOS/python");
  if (!fs.existsSync(python)) return null;
  const libDir = path.join(traceResources, "lib");
  if (!fs.existsSync(libDir)) return null;
  const pythonLib = fs
    .readdirSync(libDir)
    .find((name) => name.startsWith("python") && !name.endsWith(".zip"));
  if (!pythonLib) return null;
  return {
    python,
    bridgeRoot: path.join(libDir, pythonLib),
    traceResources,
  };
}

function resolvePythonBridgeCommand(moduleName) {
  if (process.env.TRACE_PYTHON_EXECUTABLE) {
    const args =
      process.env.TRACE_PYTHON_BRIDGE_MODE === "bridge-exe"
        ? [moduleName]
        : ["-m", moduleName];
    return {
      command: process.env.TRACE_PYTHON_EXECUTABLE,
      args,
      cwd: projectRoot(),
      bridgeRoot: null,
    };
  }

  const windowsPortable = windowsPortableLayout();
  if (windowsPortable) {
    return {
      command: windowsPortable.bridge,
      args: [moduleName],
      cwd: windowsPortable.appDir,
      bridgeRoot: null,
    };
  }

  const bundled = bundledTraceLayout();
  if (bundled) {
    return {
      command: bundled.python,
      args: ["-m", moduleName],
      cwd: bundled.traceResources,
      bridgeRoot: bundled.bridgeRoot,
    };
  }

  const devPython =
    process.platform === "win32"
      ? path.join(projectRoot(), ".venv", "Scripts", "python.exe")
      : path.join(projectRoot(), ".venv", "bin", "python");
  if (fs.existsSync(devPython)) {
    return {
      command: devPython,
      args: ["-m", moduleName],
      cwd: projectRoot(),
      bridgeRoot: path.join(projectRoot(), "code"),
    };
  }

  return {
    command: "uv",
    args: ["run", "python", "-m", moduleName],
    cwd: projectRoot(),
    bridgeRoot: path.join(projectRoot(), "code"),
  };
}

// === IPC 处理：renderer 通过 contextBridge 调这些 ===
function openDb() {
  const dbFile = dbPath();
  if (!fs.existsSync(dbFile)) {
    throw new Error(`数据库不存在: ${dbFile}`);
  }
  return new sqlite3.Database(dbFile, sqlite3.OPEN_READONLY);
}

function dbAll(sql, params = []) {
  return new Promise((resolve, reject) => {
    let db;
    try {
      db = openDb();
    } catch (err) {
      reject(err);
      return;
    }
    db.all(sql, params, (err, rows) => {
      db.close();
      if (err) reject(err);
      else resolve(rows);
    });
  });
}

function dbGet(sql, params = []) {
  return new Promise((resolve, reject) => {
    let db;
    try {
      db = openDb();
    } catch (err) {
      reject(err);
      return;
    }
    db.get(sql, params, (err, row) => {
      db.close();
      if (err) reject(err);
      else resolve(row);
    });
  });
}

function runPythonInit(payload) {
  return runPythonBridge(
    PYTHON_INIT_MODULE,
    payload,
    15000,
    "workspace init timed out",
  );
}

async function ensureWorkspaceReady() {
  if (!fs.existsSync(workspace)) {
    throw new Error(`工作区目录不存在: ${workspace}`);
  }
  if (fs.existsSync(dbPath())) {
    return;
  }
  const result = await runPythonInit({ workspace });
  if (result?.error || result?.ok === false) {
    throw new Error(
      result?.error ||
        "无法初始化 .trace 仓库；请确认已安装 uv 且项目依赖完整。",
    );
  }
  if (!fs.existsSync(dbPath())) {
    throw new Error(`初始化后仍未找到数据库: ${dbPath()}`);
  }
}

function parseCandidates(value) {
  if (!value) return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : [];
  } catch (_e) {
    return [];
  }
}

function pythonBridgeEnv(bridgeRoot) {
  const env = { ...process.env };
  env.PYTHONDONTWRITEBYTECODE = "1";
  if (
    bridgeRoot === null &&
    (env.TRACE_PYTHON_BRIDGE_MODE === "bridge-exe" || windowsPortableLayout())
  ) {
    delete env.PYTHONPATH;
    return env;
  }
  const root = bridgeRoot || path.join(projectRoot(), "code");
  if (root && !env.TRACE_PYTHON_EXECUTABLE) {
    env.PYTHONPATH = env.PYTHONPATH
      ? `${root}${path.delimiter}${env.PYTHONPATH}`
      : root;
  } else if (env.TRACE_PYTHON_EXECUTABLE && env.PYTHONPATH) {
    return env;
  } else if (env.TRACE_PYTHON_EXECUTABLE) {
    const bundled = bundledTraceLayout();
    if (bundled) {
      env.PYTHONPATH = env.PYTHONPATH
        ? `${bundled.bridgeRoot}${path.delimiter}${env.PYTHONPATH}`
        : bundled.bridgeRoot;
    }
  }
  return env;
}

function shellQuote(value) {
  const text = String(value);
  if (/^[A-Za-z0-9_/:=.,@%+-]+$/.test(text)) return text;
  return "'" + text.replace(/'/g, "'\\''") + "'";
}

function commandLine(argv) {
  return argv.map(shellQuote).join(" ");
}

function traceMcpLaunchSpec() {
  const bridge = resolvePythonBridgeCommand(TRACE_MCP_MODULE);
  const env = pythonBridgeEnv(bridge.bridgeRoot);
  const traceEnv = {};
  if (env.PYTHONPATH) traceEnv.PYTHONPATH = env.PYTHONPATH;
  if (bridge.bridgeRoot !== null && env.PYTHONDONTWRITEBYTECODE) {
    traceEnv.PYTHONDONTWRITEBYTECODE = env.PYTHONDONTWRITEBYTECODE;
  }
  return {
    command: bridge.command,
    args: [...bridge.args, "--workspace", workspace],
    cwd: bridge.cwd,
    env: traceEnv,
  };
}

function traceCodexHookLaunchSpec(phase) {
  const bridge = resolvePythonBridgeCommand(TRACE_CODEX_HOOK_MODULE);
  const env = pythonBridgeEnv(bridge.bridgeRoot);
  const traceEnv = {};
  if (env.PYTHONPATH) traceEnv.PYTHONPATH = env.PYTHONPATH;
  if (bridge.bridgeRoot !== null && env.PYTHONDONTWRITEBYTECODE) {
    traceEnv.PYTHONDONTWRITEBYTECODE = env.PYTHONDONTWRITEBYTECODE;
  }
  return {
    command: bridge.command,
    args: [...bridge.args, "--workspace", workspace, "--phase", phase],
    cwd: bridge.cwd,
    env: traceEnv,
  };
}

function codexConfigPath() {
  return path.join(userHome(), ".codex", "config.toml");
}

function codexHooksPath() {
  return path.join(userHome(), ".codex", "hooks.json");
}

function opencodeConfigPath() {
  return path.join(userHome(), ".config", "opencode", "opencode.jsonc");
}

function extractTomlSection(text, sectionName) {
  const marker = `[${sectionName}]`;
  const lines = String(text || "").split(/\r?\n/);
  const section = [];
  let active = false;
  for (const line of lines) {
    const trimmed = line.trim();
    if (/^\[[^\]]+\]$/.test(trimmed)) {
      if (trimmed === marker) {
        active = true;
        section.push(line);
        continue;
      }
      if (active) break;
    } else if (active) {
      section.push(line);
    }
  }
  return section.join("\n");
}

function inspectCodexTraceMcp() {
  const configPath = codexConfigPath();
  let text = "";
  try {
    text = fs.readFileSync(configPath, "utf-8");
  } catch (_e) {
    // Missing config is normal on a new Codex install.
  }
  const section = extractTomlSection(text, `mcp_servers.${TRACE_MCP_SERVER_NAME}`);
  const hasTraceSection = section.length > 0;
  const hasTraceServer = section.includes(TRACE_MCP_MODULE);
  const hasWorkspace = pathAppearsInText(section, workspace);
  const installed = hasTraceSection && hasTraceServer && hasWorkspace;
  return {
    configPath,
    hasTraceSection,
    hasTraceServer,
    hasWorkspace,
    installed,
  };
}

function formatTomlValue(value) {
  return JSON.stringify(String(value));
}

function formatTomlArray(values) {
  return `[${values.map(formatTomlValue).join(", ")}]`;
}

function traceCodexTomlSections() {
  const spec = traceMcpLaunchSpec();
  const lines = [
    `[mcp_servers.${TRACE_MCP_SERVER_NAME}]`,
    `command = ${formatTomlValue(spec.command)}`,
    `args = ${formatTomlArray(spec.args)}`,
  ];
  const envEntries = Object.entries(spec.env || {});
  if (envEntries.length) {
    lines.push("", `[mcp_servers.${TRACE_MCP_SERVER_NAME}.env]`);
    for (const [key, value] of envEntries) {
      lines.push(`${key} = ${formatTomlValue(value)}`);
    }
  }
  return lines.join("\n");
}

function stripTomlSections(text, sectionNames) {
  const names = new Set(sectionNames);
  const lines = String(text || "").split(/\r?\n/);
  const kept = [];
  let skip = false;
  for (const line of lines) {
    const trimmed = line.trim();
    const match = trimmed.match(/^\[([^\]]+)\]$/);
    if (match) {
      skip = names.has(match[1]);
    }
    if (!skip) kept.push(line);
  }
  return kept.join("\n").replace(/\s+$/u, "");
}

function installCodexTraceMcpConfig() {
  const configPath = codexConfigPath();
  let existing = "";
  try {
    existing = fs.readFileSync(configPath, "utf-8");
  } catch (_e) {
    existing = "";
  }
  const cleaned = stripTomlSections(existing, [
    `mcp_servers.${TRACE_MCP_SERVER_NAME}`,
    `mcp_servers.${TRACE_MCP_SERVER_NAME}.env`,
  ]);
  const next = [cleaned, traceCodexTomlSections()]
    .filter((part) => part.trim().length > 0)
    .join("\n\n");
  fs.mkdirSync(path.dirname(configPath), { recursive: true });
  fs.writeFileSync(configPath, `${next}\n`, "utf-8");
  return inspectCodexTraceMcp();
}

function loadCodexHooksConfig() {
  const hooksPath = codexHooksPath();
  try {
    return JSON.parse(fs.readFileSync(hooksPath, "utf-8"));
  } catch (_e) {
    return { hooks: {} };
  }
}

function isTraceHookEntry(entry) {
  const hooks = Array.isArray(entry?.hooks) ? entry.hooks : [];
  return hooks.some((hook) =>
    String(hook?.command || "").includes(TRACE_CODEX_HOOK_MODULE),
  );
}

function stripTraceHookEntries(entries) {
  return (Array.isArray(entries) ? entries : []).filter(
    (entry) => !isTraceHookEntry(entry),
  );
}

function hookCommand(phase) {
  const spec = traceCodexHookLaunchSpec(phase);
  const envPrefix = Object.entries(spec.env || {})
    .map(([key, value]) => `${key}=${shellQuote(value)}`)
    .join(" ");
  const prefix = envPrefix ? `${envPrefix} ` : "";
  return `${prefix}${commandLine([spec.command, ...spec.args])}`;
}

function traceHookEntry(phase) {
  const matcher =
    phase === "pre" ? "apply_patch|Edit|Write|MultiEdit" : "Bash|Shell|exec_command|apply_patch|Edit|Write|MultiEdit";
  return {
    matcher,
    hooks: [
      {
        type: "command",
        command: hookCommand(phase),
        timeout: 5,
        statusMessage:
          phase === "pre"
            ? "Trace records Codex write intent"
            : "Trace records Codex file changes",
      },
    ],
  };
}

function inspectCodexTraceHook() {
  const hooksPath = codexHooksPath();
  const config = loadCodexHooksConfig();
  const hooks = config.hooks || {};
  const allEntries = [
    ...(Array.isArray(hooks.PreToolUse) ? hooks.PreToolUse : []),
    ...(Array.isArray(hooks.PostToolUse) ? hooks.PostToolUse : []),
  ];
  const hasTraceHook = allEntries.some(isTraceHookEntry);
  const serialized = JSON.stringify(allEntries);
  const hasWorkspace = pathAppearsInText(serialized, workspace);
  const installed = hasTraceHook && hasWorkspace;
  return {
    hooksPath,
    hasTraceHook,
    hasWorkspace,
    installed,
  };
}

function installCodexTraceHookConfig() {
  const hooksPath = codexHooksPath();
  const config = loadCodexHooksConfig();
  const hooks = config.hooks && typeof config.hooks === "object" ? config.hooks : {};
  hooks.PreToolUse = [...stripTraceHookEntries(hooks.PreToolUse), traceHookEntry("pre")];
  hooks.PostToolUse = [
    ...stripTraceHookEntries(hooks.PostToolUse),
    traceHookEntry("post"),
  ];
  config.hooks = hooks;
  fs.mkdirSync(path.dirname(hooksPath), { recursive: true });
  fs.writeFileSync(hooksPath, `${JSON.stringify(config, null, 2)}\n`, "utf-8");
  return inspectCodexTraceHook();
}

function findCodexBinary() {
  const candidates = [
    process.env.CODEX_CLI_PATH,
    "/opt/homebrew/bin/codex",
    "/usr/local/bin/codex",
  ];
  for (const candidate of candidates) {
    if (candidate && fs.existsSync(candidate)) return candidate;
  }
  return "codex";
}

function findClaudeBinary() {
  const candidates = [
    process.env.CLAUDE_CLI_PATH,
    "/opt/homebrew/bin/claude",
    "/usr/local/bin/claude",
  ];
  for (const candidate of candidates) {
    if (candidate && fs.existsSync(candidate)) return candidate;
  }
  return "claude";
}

function findOpencodeBinary() {
  const candidates = [
    process.env.OPENCODE_CLI_PATH,
    "/opt/homebrew/bin/opencode",
    "/usr/local/bin/opencode",
  ];
  for (const candidate of candidates) {
    if (candidate && fs.existsSync(candidate)) return candidate;
  }
  return "opencode";
}

function codexMcpAddCommand() {
  const spec = traceMcpLaunchSpec();
  const codex = findCodexBinary();
  const args = ["mcp", "add", TRACE_MCP_SERVER_NAME];
  if (spec.env.PYTHONPATH) {
    args.push("--env", `PYTHONPATH=${spec.env.PYTHONPATH}`);
  }
  args.push("--", spec.command, ...spec.args);
  return {
    binary: codex,
    args,
    command: commandLine([codex, ...args]),
    prefix: CODEX_MCP_ADD_PREFIX,
  };
}

function claudeMcpAddCommand() {
  const spec = traceMcpLaunchSpec();
  const claude = findClaudeBinary();
  const args = ["mcp", "add", "--scope", "user", TRACE_MCP_SERVER_NAME];
  if (spec.env.PYTHONPATH) {
    args.push("-e", `PYTHONPATH=${spec.env.PYTHONPATH}`);
  }
  args.push("--", spec.command, ...spec.args);
  return {
    binary: claude,
    args,
    command: commandLine([claude, ...args]),
    prefix: CLAUDE_MCP_ADD_PREFIX,
  };
}

function opencodeMcpAddCommand() {
  const spec = traceMcpLaunchSpec();
  const opencode = findOpencodeBinary();
  const args = ["mcp", "add"];
  return {
    binary: opencode,
    args,
    command: `${commandLine([opencode, ...args])}\n${opencodeTraceConfigText()}`,
    prefix: OPENCODE_MCP_ADD_PREFIX,
  };
}

function traceMcpConfigObject() {
  const spec = traceMcpLaunchSpec();
  const config = {
    type: "local",
    command: [spec.command, ...spec.args],
    enabled: true,
  };
  if (Object.keys(spec.env || {}).length) {
    config.environment = spec.env;
  }
  return config;
}

function opencodeTraceConfigText() {
  return JSON.stringify({ mcp: { [TRACE_MCP_SERVER_NAME]: traceMcpConfigObject() } }, null, 2);
}

function stripJsonComments(text) {
  let output = "";
  let inString = false;
  let escaped = false;
  let inLineComment = false;
  let inBlockComment = false;

  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    const next = text[i + 1];

    if (inLineComment) {
      if (char === "\n" || char === "\r") {
        inLineComment = false;
        output += char;
      }
      continue;
    }

    if (inBlockComment) {
      if (char === "*" && next === "/") {
        inBlockComment = false;
        i += 1;
      }
      continue;
    }

    if (inString) {
      output += char;
      if (escaped) {
        escaped = false;
      } else if (char === "\\") {
        escaped = true;
      } else if (char === "\"") {
        inString = false;
      }
      continue;
    }

    if (char === "\"") {
      inString = true;
      output += char;
      continue;
    }
    if (char === "/" && next === "/") {
      inLineComment = true;
      i += 1;
      continue;
    }
    if (char === "/" && next === "*") {
      inBlockComment = true;
      i += 1;
      continue;
    }
    output += char;
  }

  return output;
}

function stripTrailingJsonCommas(text) {
  let output = "";
  let inString = false;
  let escaped = false;

  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];

    if (inString) {
      output += char;
      if (escaped) {
        escaped = false;
      } else if (char === "\\") {
        escaped = true;
      } else if (char === "\"") {
        inString = false;
      }
      continue;
    }

    if (char === "\"") {
      inString = true;
      output += char;
      continue;
    }

    if (char === ",") {
      let j = i + 1;
      while (j < text.length && /\s/.test(text[j])) j += 1;
      if (text[j] === "}" || text[j] === "]") continue;
    }

    output += char;
  }

  return output;
}

function parseJsonLikeObject(text) {
  const parsed = JSON.parse(stripTrailingJsonCommas(stripJsonComments(text)));
  return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
}

function loadJsonObject(filePath) {
  try {
    return parseJsonLikeObject(fs.readFileSync(filePath, "utf-8"));
  } catch (_e) {
    return {};
  }
}

function inspectClaudeTraceMcp() {
  const mcpJsonPath = path.join(workspace, ".mcp.json");
  const userConfigPath = path.join(userHome(), ".claude.json");
  const configPaths = [userConfigPath, mcpJsonPath];
  const texts = configPaths.map((configPath) => {
    try {
      return fs.readFileSync(configPath, "utf-8");
    } catch (_e) {
      return "";
    }
  });
  const serialized = texts.join("\n");
  const installed = serialized.includes(TRACE_MCP_MODULE) && pathAppearsInText(serialized, workspace);
  return {
    configPath: installed && texts[0].includes(TRACE_MCP_MODULE) ? userConfigPath : mcpJsonPath,
    hasTraceSection: serialized.includes(`"${TRACE_MCP_SERVER_NAME}"`),
    hasTraceServer: serialized.includes(TRACE_MCP_MODULE),
    hasWorkspace: pathAppearsInText(serialized, workspace),
    installed,
  };
}

function inspectOpencodeTraceMcp() {
  const configPath = opencodeConfigPath();
  const config = loadJsonObject(configPath);
  const trace = config?.mcp?.[TRACE_MCP_SERVER_NAME];
  const serialized = JSON.stringify(trace || {});
  return {
    configPath,
    hasTraceSection: Boolean(trace),
    hasTraceServer: serialized.includes(TRACE_MCP_MODULE),
    hasWorkspace: pathAppearsInText(serialized, workspace),
    installed: serialized.includes(TRACE_MCP_MODULE) && serialized.includes(workspace),
  };
}

function installOpencodeTraceMcpConfig() {
  const configPath = opencodeConfigPath();
  const config = loadJsonObject(configPath);
  const mcp = config.mcp && typeof config.mcp === "object" ? config.mcp : {};
  mcp[TRACE_MCP_SERVER_NAME] = traceMcpConfigObject();
  config.mcp = mcp;
  fs.mkdirSync(path.dirname(configPath), { recursive: true });
  fs.writeFileSync(configPath, `${JSON.stringify(config, null, 2)}\n`, "utf-8");
  return inspectOpencodeTraceMcp();
}

function mcpSetupRows() {
  const spec = traceMcpLaunchSpec();
  const stdioCommand = commandLine([spec.command, ...spec.args]);
  const envLine = spec.env.PYTHONPATH ? `PYTHONPATH=${spec.env.PYTHONPATH}\n` : "";
  const codexState = inspectCodexTraceMcp();
  const codexHookState = inspectCodexTraceHook();
  const claudeState = inspectClaudeTraceMcp();
  const opencodeState = inspectOpencodeTraceMcp();
  const codexCommand = codexMcpAddCommand();
  const claudeCommand = claudeMcpAddCommand();
  const opencodeCommand = opencodeMcpAddCommand();
  const codexInstalled = codexState.installed && codexHookState.installed;
  const codexPartial =
    !codexInstalled &&
    (codexState.hasTraceSection ||
      codexHookState.hasTraceHook ||
      codexState.installed ||
      codexHookState.installed);

  return [
    {
      id: "codex",
      name: "Codex",
      tool: TRACE_MCP_TOOL,
      installed: codexInstalled,
      status: codexInstalled
        ? "installed"
        : codexPartial
          ? "partial"
          : "not-installed",
      status_label: codexInstalled
        ? "已添加"
        : codexPartial
          ? "待修复"
          : "可一键添加",
      canAutoInstall: true,
      action_label: codexInstalled ? "已添加" : "一键添加",
      command: codexCommand.command,
      command_prefix: codexCommand.prefix,
      config_path: codexState.configPath,
      hook_path: codexHookState.hooksPath,
      hook_command: hookCommand("pre"),
      description: codexInstalled
        ? "Codex 已配置 Trace MCP 与 Trace hooks，新开会话后会主动上报改动文件。"
        : codexPartial
          ? "Codex 已有部分或旧 Trace 配置；点击后会替换旧 trace 配置并补齐 hooks。"
          : "点击后写入 Codex MCP 与 hooks 配置；重启 Codex 后在 /hooks 信任一次即可生效。",
    },
    {
      id: "claude",
      name: "Claude Code",
      tool: TRACE_MCP_TOOL,
      installed: claudeState.installed,
      status: claudeState.installed ? "installed" : "not-installed",
      status_label: claudeState.installed ? "已添加" : "可一键添加",
      canAutoInstall: true,
      action_label: claudeState.installed ? "已添加" : "一键添加",
      command: claudeCommand.command,
      command_prefix: claudeCommand.prefix,
      config_path: claudeState.configPath,
      description:
        claudeState.installed
          ? "Claude Code 已配置 Trace MCP；如显示 Pending approval，请在 Claude 中批准一次。"
          : "点击后调用 claude mcp add 写入用户级 Trace MCP；重启 Claude 后批准一次即可生效。",
    },
    {
      id: "opencode",
      name: "OpenCode",
      tool: TRACE_MCP_TOOL,
      installed: opencodeState.installed,
      status: opencodeState.installed ? "installed" : "not-installed",
      status_label: opencodeState.installed ? "已添加" : "可一键添加",
      canAutoInstall: true,
      action_label: opencodeState.installed ? "已添加" : "一键添加",
      command: opencodeCommand.command,
      command_prefix: opencodeCommand.prefix,
      config_path: opencodeState.configPath,
      description:
        opencodeState.installed
          ? "OpenCode 已配置 Trace MCP；重启 OpenCode 后生效。"
          : "点击后写入 ~/.config/opencode/opencode.jsonc，重启 OpenCode 后生效。",
    },
    {
      id: "other",
      name: "Other Agents",
      tool: TRACE_MCP_TOOL,
      installed: false,
      status: "manual",
      status_label: "复制配置",
      canAutoInstall: false,
      action_label: "复制配置",
      command: `${envLine}${stdioCommand}`,
      config_path: "",
      description:
        "其他的 agent 请复制到配置文件；支持 MCP stdio 的 agent 可使用这条 Trace server 命令。",
    },
  ];
}

function runMcpInstallCommand(command, args) {
  return new Promise((resolve) => {
    const child = spawn(command, args, {
      cwd: projectRoot(),
      env: process.env,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    let settled = false;
    const timeout = setTimeout(() => {
      if (settled) return;
      settled = true;
      child.kill();
      resolve({ ok: false, error: "mcp install timed out" });
    }, 20000);

    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });
    child.on("error", (err) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      resolve({ ok: false, error: String(err) });
    });
    child.on("close", (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      if (code !== 0) {
        resolve({
          ok: false,
          error: stderr.trim() || stdout.trim() || `mcp install exited ${code}`,
          stdout: stdout.trim(),
          stderr: stderr.trim(),
        });
        return;
      }
      resolve({
        ok: true,
        stdout: stdout.trim(),
        stderr: stderr.trim(),
      });
    });
  });
}

function runPythonBridge(moduleName, payload, timeoutMs, timeoutMessage) {
  return new Promise((resolve) => {
    const bridge = resolvePythonBridgeCommand(moduleName);
    const child = spawn(bridge.command, bridge.args, {
      cwd: bridge.cwd,
      env: pythonBridgeEnv(bridge.bridgeRoot),
      stdio: ["pipe", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    let settled = false;
    const timeout = setTimeout(() => {
      if (settled) return;
      settled = true;
      child.kill();
      resolve({ ok: false, error: timeoutMessage });
    }, timeoutMs);

    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });
    child.on("error", (err) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      resolve({ ok: false, error: String(err) });
    });
    child.on("close", (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      if (code !== 0) {
        resolve({
          ok: false,
          error:
            stderr.trim() ||
            stdout.trim() ||
            `diff handler exited with ${code}`,
        });
        return;
      }
      try {
        resolve(JSON.parse(stdout));
      } catch (err) {
        resolve({
          ok: false,
          error: `invalid diff handler response: ${String(err)}`,
        });
      }
    });
    child.stdin.end(JSON.stringify(payload));
  });
}

function runPythonDiff(payload) {
  return runPythonBridge(
    PYTHON_DIFF_MODULE,
    payload,
    10000,
    "diff handler timed out",
  );
}

function runPythonDiffs(payload) {
  return runPythonBridge(
    PYTHON_DIFF_MODULE,
    payload,
    30000,
    "diff handler timed out",
  );
}

function runPythonRestore(payload) {
  return runPythonBridge(
    PYTHON_RESTORE_MODULE,
    payload,
    15000,
    "restore handler timed out",
  );
}

function runPythonReassign(payload) {
  return runPythonBridge(
    PYTHON_REASSIGN_MODULE,
    payload,
    10000,
    "reassign handler timed out",
  );
}

function runPythonRevertAgent(payload) {
  return runPythonBridge(
    PYTHON_REVERT_AGENT_MODULE,
    payload,
    60000,
    "revert agent handler timed out",
  );
}

ipcMain.handle("list-commits", async () => {
  try {
    const rows = await dbAll(
      "SELECT id, time, author_agent, detection_method, confidence, candidates, summary FROM commits ORDER BY id DESC LIMIT 200",
    );
    return rows.map((row) => ({
      ...row,
      candidates: parseCandidates(row.candidates),
    }));
  } catch (e) {
    return { error: String(e) };
  }
});

ipcMain.handle("list-agents", async () => {
  try {
    return await dbAll(`
      SELECT
        a.name,
        a.category,
        a.display_name,
        a.color,
        COALESCE(stats.commit_count, 0) AS commit_count,
        stats.last_time
      FROM agents a
      LEFT JOIN (
        SELECT author_agent, COUNT(*) AS commit_count, MAX(time) AS last_time
        FROM commits
        GROUP BY author_agent
      ) stats ON stats.author_agent = a.name
      ORDER BY commit_count DESC, a.name ASC
    `);
  } catch (e) {
    return { error: String(e) };
  }
});

ipcMain.handle("get-manifest", async (_e, commitId) => {
  try {
    return await dbAll(
      "SELECT file_path, blob_hash FROM snapshots WHERE commit_id = ?",
      [commitId],
    );
  } catch (e) {
    return { error: String(e) };
  }
});

ipcMain.handle("get-prev-commit-id", async (_e, commitId) => {
  try {
    const rows = await dbAll(
      "SELECT id FROM commits WHERE id < ? ORDER BY id DESC LIMIT 1",
      [commitId],
    );
    return rows.length ? rows[0].id : null;
  } catch (e) {
    return { error: String(e) };
  }
});

ipcMain.handle("render-diff", async (_e, filePath, prevHash, curHash) => {
  return await runPythonDiff({
    workspace,
    file_path: filePath,
    prev_hash: prevHash || null,
    cur_hash: curHash || null,
  });
});

ipcMain.handle("render-diffs", async (_e, files) => {
  return await runPythonDiffs({
    workspace,
    files: Array.isArray(files) ? files : [],
  });
});

ipcMain.handle("restore-file", async (_e, commitId, filePath) => {
  return await runPythonRestore({
    workspace,
    commit_id: commitId,
    file_path: filePath,
    backup_current: true,
  });
});

ipcMain.handle("reassign-commit", async (_e, commitId, newAgent) => {
  return await runPythonReassign({
    workspace,
    commit_id: commitId,
    new_agent: newAgent,
  });
});

ipcMain.handle("preview-revert-agent", async (_e, agent) => {
  return await runPythonRevertAgent({
    workspace,
    agent,
    preview: true,
  });
});

ipcMain.handle("revert-agent", async (_e, agent) => {
  return await runPythonRevertAgent({
    workspace,
    agent,
    backup_current: true,
  });
});

ipcMain.handle("get-workspace", () => workspace);

ipcMain.handle("list-mcp-setup", () => {
  try {
    return mcpSetupRows();
  } catch (e) {
    return { error: String(e) };
  }
});

ipcMain.handle("install-mcp-server", async (_e, serverId) => {
  if (!["codex", "claude", "opencode"].includes(serverId)) {
    return {
      ok: false,
      error: "这个 agent 暂不支持自动添加；请复制配置到对应配置文件。",
    };
  }

  if (serverId === "claude") {
    const state = inspectClaudeTraceMcp();
    const command = claudeMcpAddCommand();
    if (state.installed) {
      return {
        ok: true,
        already_installed: true,
        server_id: serverId,
        command: command.command,
        config_path: state.configPath,
        restart_required: true,
      };
    }
    if (rendererSmokeTest) {
      return {
        ok: true,
        test: true,
        server_id: serverId,
        command: command.command,
        config_path: state.configPath,
      };
    }
    const result = await runMcpInstallCommand(command.binary, command.args);
    return {
      ...result,
      server_id: serverId,
      command: command.command,
      config_path: state.configPath,
      restart_required: result.ok,
      approval_required: result.ok,
    };
  }

  if (serverId === "opencode") {
    const state = inspectOpencodeTraceMcp();
    const command = opencodeMcpAddCommand();
    if (state.installed) {
      return {
        ok: true,
        already_installed: true,
        server_id: serverId,
        command: command.command,
        config_path: state.configPath,
        restart_required: true,
      };
    }
    if (rendererSmokeTest) {
      return {
        ok: true,
        test: true,
        server_id: serverId,
        command: command.command,
        config_path: state.configPath,
      };
    }
    const nextState = installOpencodeTraceMcpConfig();
    return {
      ok: nextState.installed,
      server_id: serverId,
      command: command.command,
      config_path: nextState.configPath,
      restart_required: true,
    };
  }

  const state = inspectCodexTraceMcp();
  const hookState = inspectCodexTraceHook();
  const command = codexMcpAddCommand();
  if (state.installed && hookState.installed) {
    return {
      ok: true,
      already_installed: true,
      server_id: serverId,
      command: command.command,
      config_path: state.configPath,
      hook_path: hookState.hooksPath,
    };
  }
  if (rendererSmokeTest) {
    return {
      ok: true,
      test: true,
      server_id: serverId,
      command: command.command,
      config_path: state.configPath,
      hook_path: hookState.hooksPath,
    };
  }

  const mcpResult = installCodexTraceMcpConfig();
  const hookResult = installCodexTraceHookConfig();
  const result = {
    ok: mcpResult.installed && hookResult.installed,
    replaced_existing_mcp: state.hasTraceSection && !state.installed,
    replaced_existing_hook: hookState.hasTraceHook && !hookState.installed,
  };
  return {
    ...result,
    server_id: serverId,
    command: command.command,
    config_path: mcpResult.configPath,
    hook_path: hookResult.hooksPath,
    hook_installed: hookResult.installed,
    restart_required: result.ok,
  };
});

ipcMain.handle("get-workspace-summary", async () => {
  try {
    const commits = await dbGet("SELECT COUNT(*) AS n FROM commits");
    const snapshots = await dbGet("SELECT COUNT(*) AS n FROM snapshots");
    const agents = await dbGet("SELECT COUNT(*) AS n FROM agents");
    return {
      workspace,
      db_path: dbPath(),
      commit_count: commits.n,
      snapshot_count: snapshots.n,
      agent_count: agents.n,
    };
  } catch (e) {
    return { error: String(e), workspace, db_path: dbPath() };
  }
});

ipcMain.handle("open-github", async () => {
  try {
    if (rendererSmokeTest) {
      return { ok: true, url: GITHUB_URL, test: true };
    }
    await shell.openExternal(GITHUB_URL);
    return { ok: true, url: GITHUB_URL };
  } catch (e) {
    return { error: String(e), url: GITHUB_URL };
  }
});

async function runRendererSmokeTest(win) {
  try {
    await win.webContents.executeJavaScript(`
      new Promise(resolve => {
        if (document.readyState === 'complete') resolve();
        else window.addEventListener('load', resolve, { once: true });
      })
    `);
    const result = await win.webContents.executeJavaScript(`
      (async () => {
        const wait = (ms = 150) => new Promise(resolve => setTimeout(resolve, ms));
        const waitFor = async (predicate, label) => {
          const started = Date.now();
          while (Date.now() - started < 3000) {
            if (predicate()) return true;
            await wait(50);
          }
          throw new Error('timed out waiting for ' + label);
        };
        const click = async (selector) => {
          const el = document.querySelector(selector);
          if (!el) throw new Error('missing selector: ' + selector);
          el.click();
          await wait(50);
        };

        await waitFor(
          () => document.querySelectorAll('.timeline-row').length > 0,
          'timeline rows'
        );
        const initialRows = document.querySelectorAll('.timeline-row').length;
        await waitFor(
          () => document.querySelectorAll('.version-node').length > 0
            && document.querySelectorAll('.graph-connection').length > 0,
          'commit version graph'
        );
        const graphNodes = document.querySelectorAll('.version-node').length;
        const graphConnections = document.querySelectorAll('.graph-connection').length;
        const firstGraphNode = document.querySelector('.version-node');
        firstGraphNode.click();
        await wait(80);
        const graphNodeSelectable = firstGraphNode.classList.contains('selected')
          || document.getElementById('status-line').textContent.includes('commit #');

        await click('[data-view="agents"]');
        await waitFor(
          () => !document.getElementById('detail-view').classList.contains('hidden')
            && document.getElementById('detail-view').textContent.includes('AGENTS'),
          'agents panel'
        );
        const agentsVisible = true;

        await click('[data-view="workspace"]');
        await waitFor(
          () => document.getElementById('detail-view').textContent.includes('WORKSPACE'),
          'workspace panel'
        );
        const workspaceVisible = true;

        await click('[data-view="mcp"]');
        await waitFor(
          () => document.getElementById('detail-view').textContent.includes('MCP')
            && document.querySelectorAll('.mcp-card').length > 0,
          'mcp setup panel'
        );
        const mcpSetupVisible = true;

        await click('[data-action="show-diff"]');
        await waitFor(
          () => document.querySelector('[data-action="show-diff"]').classList.contains('active')
            && !document.getElementById('commit-view').classList.contains('hidden'),
          'diff focus'
        );
        const diffFocused = true;
        await waitFor(
          () => document.querySelectorAll('.diff-file-header').length > 0,
          'diff file headers'
        );
        const diffFileHeadersVisible = true;
        await waitFor(
          () => {
            const restoreButton = document.querySelector('[data-action="restore-file"]');
            return restoreButton && restoreButton.textContent.includes('回退');
          },
          'restore button'
        );
        const restoreButtonVisible = true;

        const openGithubButton = document.querySelector('[data-action="open-github"]');
        if (!openGithubButton) throw new Error('missing selector: [data-action="open-github"]');
        const githubResult = await window.api.openGithub();
        const githubStatus = Boolean(
          githubResult && githubResult.ok === true && String(githubResult.url || '').includes('github.com')
        );

        await click('[data-view="commits"]');
        await waitFor(
          () => !document.getElementById('commit-view').classList.contains('hidden'),
          'commits panel'
        );
        const commitsVisible = true;

        return { initialRows, graphNodes, graphConnections, graphNodeSelectable, agentsVisible, workspaceVisible, mcpSetupVisible, diffFocused, diffFileHeadersVisible, restoreButtonVisible, githubStatus, commitsVisible };
      })()
    `);
    console.log(JSON.stringify({ rendererSmokeTest: result }));
    const ok =
      result.initialRows > 0 &&
      result.graphNodes > 0 &&
      result.graphConnections > 0 &&
      result.graphNodeSelectable &&
      result.agentsVisible &&
      result.workspaceVisible &&
      result.mcpSetupVisible &&
      result.diffFocused &&
      result.diffFileHeadersVisible &&
      result.restoreButtonVisible &&
      result.githubStatus &&
      result.commitsVisible;
    app.exit(ok ? 0 : 1);
  } catch (e) {
    console.error("renderer smoke test failed:", e);
    app.exit(1);
  }
}

function createWindow() {
  const win = new BrowserWindow(createWindowOptions());
  if (rendererDevServerUrl) {
    win.loadURL(rendererDevServerUrl);
  } else {
    win.loadFile(path.join(__dirname, "renderer-dist", "index.html"));
  }
  if (rendererSmokeTest) {
    win.webContents.once("did-finish-load", () => runRendererSmokeTest(win));
  }
  // 调试用：取消注释打开 DevTools
  // win.webContents.openDevTools();
}

function createWindowOptions() {
  const baseOptions = {
    width: 1200,
    height: 780,
    minWidth: 900,
    minHeight: 600,
    backgroundColor: "#0a0a0a",
    show: !rendererSmokeTest,
    title: "Trace",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  };
  if (process.platform === "darwin") {
    const macWindowOptions = {
      backgroundColor: "#00000000",
      transparent: true,
      vibrancy: "under-window",
      visualEffectState: "active",
      titleBarStyle: "hiddenInset",
    };
    return { ...baseOptions, ...macWindowOptions };
  }
  return baseOptions;
}

function notifyWorkspaceChanged(nextWorkspace) {
  for (const win of BrowserWindow.getAllWindows()) {
    win.webContents.send("workspace-changed", nextWorkspace);
  }
}

function refreshWorkspaceFromState() {
  const nextWorkspace = loadPersistedWorkspace();
  if (!nextWorkspace || nextWorkspace === workspace) return;
  workspace = nextWorkspace;
  notifyWorkspaceChanged(workspace);
}

function watchWorkspaceState() {
  const file = stateFilePath();
  try {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    if (!fs.existsSync(file)) {
      fs.writeFileSync(file, "{}", "utf-8");
    }
    workspaceWatcher = fs.watch(file, { persistent: false }, () => {
      setTimeout(refreshWorkspaceFromState, 100);
    });
  } catch (e) {
    console.warn("workspace state watcher unavailable:", e);
  }
}

if (IS_TEST_IMPORT) {
  module.exports._test = {
    commandLine,
    createWindowOptions,
    hookCommand,
    installCodexTraceHookConfig,
    installCodexTraceMcpConfig,
    inspectCodexTraceHook,
    inspectCodexTraceMcp,
    mcpSetupRows,
    traceCodexHookLaunchSpec,
    traceMcpLaunchSpec,
    windowsPortableLayout,
  };
} else {
  app.whenReady().then(async () => {
    try {
      await ensureWorkspaceReady();
    } catch (e) {
      dialog.showErrorBox("Trace", String(e));
      app.exit(1);
      return;
    }
    createWindow();
    watchWorkspaceState();
    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
  });

  app.on("before-quit", () => {
    if (workspaceWatcher) {
      workspaceWatcher.close();
      workspaceWatcher = null;
    }
  });

  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") app.quit();
  });
}
