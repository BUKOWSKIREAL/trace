<template>
    <header class="topbar">
        <div class="prompt">
            <span class="host">trace.local</span
            ><span class="prompt-sep">:~</span
            ><span class="prompt-sep"> $ </span><span class="cursor">█</span>
        </div>
        <div class="top-actions">
            <nav class="nav" aria-label="主导航">
                <button
                    class="nav-item"
                    :class="{ active: activeShell === 'commits' }"
                    type="button"
                    data-view="commits"
                    @click="showCommits"
                >
                    commits
                </button>
                <button
                    class="nav-item"
                    :class="{ active: activeShell === 'agents' }"
                    type="button"
                    data-view="agents"
                    @click="showAgents"
                >
                    agents
                </button>
                <button
                    class="nav-item"
                    :class="{ active: activeShell === 'workspace' }"
                    type="button"
                    data-view="workspace"
                    @click="showWorkspace"
                >
                    workspace
                </button>
                <button
                    class="nav-item"
                    :class="{ active: activeShell === 'mcp' }"
                    type="button"
                    data-view="mcp"
                    @click="showMcpSetup"
                >
                    mcp
                </button>
            </nav>
            <button
                class="refresh-button"
                type="button"
                data-action="refresh"
                :disabled="refreshLoading"
                @click="manualRefresh"
            >
                {{ refreshLoading ? "refreshing" : "refresh" }}
            </button>
            <div class="theme-toggle" aria-label="主题切换">
                <button
                    class="theme-option"
                    :class="{ active: theme === 'system' }"
                    type="button"
                    @click="setTheme('system')"
                >
                    system
                </button>
                <button
                    class="theme-option"
                    :class="{ active: theme === 'dark' }"
                    type="button"
                    @click="setTheme('dark')"
                >
                    dark
                </button>
                <button
                    class="theme-option"
                    :class="{ active: theme === 'light' }"
                    type="button"
                    @click="setTheme('light')"
                >
                    light
                </button>
            </div>
        </div>
    </header>

    <div class="hairline"></div>

    <main class="container">
        <section class="hero">
            <div class="hero-inner">
                <h1 class="hero-title">Trace</h1>
                <p class="hero-sub">
                    <span class="slashes">//</span> 多 CLI Agent 协作版本追踪器
                </p>
                <p class="hero-sub dim">
                    <span class="slashes">//</span> workspace:
                    <span id="ws-path">{{ workspacePath }}</span>
                </p>
                <div class="hero-links" aria-label="快速操作">
                    <button
                        class="chip"
                        :class="{ active: activeShell === 'commits' }"
                        type="button"
                        data-view="commits"
                        @click="showCommits"
                    >
                        <span>[</span> commits <span>]</span>
                    </button>
                    <button
                        class="chip"
                        :class="{ active: activeShell === 'agents' }"
                        type="button"
                        data-view="agents"
                        @click="showAgents"
                    >
                        <span>[</span> agents <span>]</span>
                    </button>
                    <button
                        class="chip"
                        :class="{ active: activeShell === 'diff' }"
                        type="button"
                        data-action="show-diff"
                        @click="showDiff"
                    >
                        <span>[</span> diff <span>]</span>
                    </button>
                    <button
                        class="chip"
                        type="button"
                        data-action="open-github"
                        @click="openGithub"
                    >
                        <span>[</span> github <span>]</span>
                    </button>
                    <button
                        class="chip"
                        :class="{ active: activeShell === 'mcp' }"
                        type="button"
                        data-view="mcp"
                        @click="showMcpSetup"
                    >
                        <span>[</span> mcp <span>]</span>
                    </button>
                </div>
                <div v-if="mcpNeedsSetup" class="mcp-startup-tip">
                    <span>
                        // MCP 未配置：agent 暂时不会主动告诉 Trace 它改了哪些文件
                    </span>
                    <button
                        class="action-link"
                        type="button"
                        data-view="mcp"
                        @click="showMcpSetup"
                    >
                        设置 MCP
                    </button>
                </div>
                <p class="hero-status" :class="statusTone" id="status-line">
                    // {{ statusMessage }}
                </p>
            </div>
        </section>

        <section
            class="panes"
            id="commit-view"
            :class="{ hidden: currentView !== 'commits' }"
        >
            <div class="pane pane-timeline">
                <h2 class="pane-title">TIMELINE</h2>
                <div class="pane-body" id="timeline">
                    <p v-if="timelineError" class="empty">
                        // 读取数据库失败：{{ timelineError }}
                    </p>
                    <p v-else-if="commits.length === 0" class="empty">
                        // 暂无 commit。改一改 workspace 里的文件试试看
                    </p>
                    <div
                        v-else
                        class="commit-version-graph"
                        aria-label="commit 版本图"
                    >
                        <div class="graph-head">
                            <span class="graph-title">VERSION GRAPH</span>
                            <span class="graph-caption"
                                >{{ graphCommits.length }} recent versions</span
                            >
                        </div>
                        <div class="graph-canvas">
                            <svg
                                class="graph-lines"
                                viewBox="0 0 100 100"
                                preserveAspectRatio="none"
                                aria-hidden="true"
                            >
                                <line
                                    v-for="edge in graphConnections"
                                    :key="edge.id"
                                    class="graph-connection"
                                    :class="{
                                        active:
                                            edge.fromId === currentCommitId ||
                                            edge.toId === currentCommitId,
                                    }"
                                    :x1="edge.x1"
                                    :y1="edge.y1"
                                    :x2="edge.x2"
                                    :y2="edge.y2"
                                    :style="{ '--edge-index': edge.index }"
                                />
                            </svg>
                            <button
                                v-for="commit in graphCommits"
                                :key="`graph-${commit.id}`"
                                class="version-node"
                                :class="{
                                    selected: currentCommitId === commit.id,
                                    latest: commit.isLatest,
                                }"
                                type="button"
                                :style="graphNodeStyle(commit)"
                                :title="`commit #${commit.id} · ${agentLabel(commit)} · ${formatTime(commit.time)}`"
                                @click="onSelectCommit(commit.id)"
                            >
                                <span
                                    class="version-node-pulse"
                                    aria-hidden="true"
                                ></span>
                                <span
                                    class="version-node-dot"
                                    aria-hidden="true"
                                ></span>
                                <span class="version-node-label"
                                    >#{{ commit.id }}</span
                                >
                            </button>
                        </div>
                    </div>
                    <button
                        v-for="commit in commits"
                        :key="commit.id"
                        class="timeline-row"
                        :class="{ selected: currentCommitId === commit.id }"
                        type="button"
                        :data-id="commit.id"
                        @click="onSelectCommit(commit.id)"
                    >
                        <span class="tr-time">{{
                            formatTime(commit.time)
                        }}</span>
                        <span
                            class="tr-agent"
                            :class="[
                                agentClass(commit.author_agent),
                                { uncertain: isUncertain(commit) },
                            ]"
                            :title="agentTitle(commit)"
                            >{{ agentLabel(commit) }}</span
                        >
                        <span class="tr-summary">{{
                            commit.summary || ""
                        }}</span>
                    </button>
                    <div
                        v-if="selectedUncertainCommit"
                        class="reassign-panel"
                    >
                        <p class="panel-meta">
                            低置信度 commit #{{ selectedUncertainCommit.id }}，
                            候选：{{ candidatesOf(selectedUncertainCommit).join(", ") }}
                        </p>
                        <div class="panel-actions">
                            <select
                                v-model="reassignChoice"
                                class="reassign-select"
                            >
                                <option
                                    v-for="name in reassignOptions"
                                    :key="name"
                                    :value="name"
                                >
                                    {{ name }}
                                </option>
                            </select>
                            <button
                                class="action-link"
                                type="button"
                                :disabled="reassignLoading"
                                @click="reassignSelectedCommit"
                            >
                                {{
                                    reassignLoading
                                        ? "修正中…"
                                        : "指定归属"
                                }}
                            </button>
                        </div>
                    </div>
                </div>
            </div>

            <div class="pane pane-diff" :class="{ flash: diffFlash }">
                <h2 class="pane-title">DIFF</h2>
                <div class="pane-body" id="diff">
                    <p v-if="diffLoading" class="empty">// 正在加载 diff…</p>
                    <p v-else-if="diffError" class="empty">
                        // 渲染 diff 失败：{{ diffError }}
                    </p>
                    <p v-else-if="diffRows.length === 0" class="empty">
                        // 选中左边任意 commit 查看 diff
                    </p>
                    <template
                        v-else
                        v-for="(row, index) in diffRows"
                        :key="`${row.type}-${index}-${row.text}`"
                    >
                        <div
                            v-if="row.type === 'file'"
                            class="diff-file-header"
                            :class="row.statusClass"
                        >
                            <span class="diff-file-path"
                                >{{ row.status }} {{ row.path }}</span
                            >
                            <button
                                v-if="row.canRestore"
                                class="rollback-button"
                                type="button"
                                data-action="restore-file"
                                :disabled="
                                    restoreLoadingKey ===
                                    fileKey(row.commitId, row.path)
                                "
                                @click="restoreFile(row.commitId, row.path)"
                            >
                                {{
                                    restoreLoadingKey ===
                                    fileKey(row.commitId, row.path)
                                        ? "回退中"
                                        : "回退"
                                }}
                            </button>
                        </div>
                        <div v-else class="diff-line" :class="row.tag">
                            {{ row.prefix }} {{ row.text }}
                        </div>
                    </template>
                </div>
            </div>
        </section>

        <section
            class="info-panel"
            id="detail-view"
            :class="{ hidden: currentView === 'commits' }"
            aria-live="polite"
        >
            <template v-if="currentView === 'agents'">
                <p v-if="detailLoading" class="empty">
                    // 正在加载 agent 统计…
                </p>
                <p v-else-if="detailError" class="empty">
                    // 读取 agent 信息失败：{{ detailError }}
                </p>
                <template v-else>
                    <div class="panel-heading">
                        <h2>[ AGENTS ]</h2>
                        <span class="panel-meta"
                            >{{ activeAgentCount }} active /
                            {{ visibleAgents.length }} registered</span
                        >
                    </div>
                    <div class="stat-grid">
                        <div class="stat-card">
                            <div class="stat-label">commits</div>
                            <div class="stat-value">
                                {{ totalAgentCommits }}
                            </div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-label">active</div>
                            <div class="stat-value">{{ activeAgentCount }}</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-label">known</div>
                            <div class="stat-value">
                                {{ visibleAgents.length }}
                            </div>
                        </div>
                    </div>
                    <div class="agent-grid">
                        <article
                            v-for="agent in visibleAgents"
                            :key="agent.name"
                            class="agent-card"
                            :class="agentClass(agent.name)"
                        >
                            <div class="agent-name">
                                {{
                                    agent.display_name ||
                                    agent.name ||
                                    "unknown"
                                }}
                            </div>
                            <div class="agent-label">
                                {{ agent.name || "unknown" }} /
                                {{ agent.category || "agent" }}
                            </div>
                            <div class="panel-meta">
                                {{ Number(agent.commit_count || 0) }} commits ·
                                last {{ formatLast(agent.last_time) }}
                            </div>
                            <button
                                v-if="
                                    agent.name &&
                                    !['human', 'unknown'].includes(agent.name)
                                "
                                class="rollback-button"
                                type="button"
                                :disabled="revertLoadingAgent === agent.name"
                                @click="revertAgent(agent.name)"
                            >
                                {{
                                    revertLoadingAgent === agent.name
                                        ? "撤销中…"
                                        : "撤销此 Agent 变更"
                                }}
                            </button>
                        </article>
                    </div>
                </template>
            </template>

            <template v-else-if="currentView === 'workspace'">
                <p v-if="detailLoading" class="empty">
                    // 正在加载 workspace 状态…
                </p>
                <p v-else-if="detailError" class="empty">
                    // 读取 workspace 信息失败：{{ detailError }}
                </p>
                <template v-else>
                    <div class="panel-heading">
                        <h2>[ WORKSPACE ]</h2>
                        <span class="panel-meta">local repository</span>
                    </div>
                    <div class="workspace-grid">
                        <template v-for="row in workspaceRows" :key="row.key">
                            <div class="workspace-key">{{ row.key }}</div>
                            <div class="workspace-value">{{ row.value }}</div>
                        </template>
                    </div>
                    <div class="panel-actions">
                        <button
                            class="action-link"
                            type="button"
                            data-view="commits"
                            @click="showCommits"
                        >
                            back to commits
                        </button>
                        <button
                            class="action-link"
                            type="button"
                            data-action="open-github"
                            @click="openGithub"
                        >
                            open github
                        </button>
                    </div>
                </template>
            </template>

            <template v-else-if="currentView === 'mcp'">
                <p v-if="detailLoading" class="empty">
                    // 正在检测 MCP server 配置…
                </p>
                <p v-else-if="detailError" class="empty">
                    // 读取 MCP 配置失败：{{ detailError }}
                </p>
                <template v-else>
                    <div class="panel-heading">
                        <h2>[ MCP ]</h2>
                        <span class="panel-meta"
                            >tool: trace_record_files</span
                        >
                    </div>
                    <div class="mcp-grid">
                        <article
                            v-for="server in mcpServers"
                            :key="server.id"
                            class="mcp-card"
                            :class="server.status"
                        >
                            <div class="mcp-card-head">
                                <div>
                                    <div class="agent-name">
                                        {{ server.name }}
                                    </div>
                                    <div class="agent-label">
                                        {{ server.tool }}
                                    </div>
                                </div>
                                <span
                                    class="mcp-status"
                                    :class="{ installed: server.installed }"
                                    >{{ server.status_label }}</span
                                >
                            </div>
                            <p class="panel-meta">
                                {{ server.description }}
                            </p>
                            <pre class="mcp-command">{{
                                server.command
                            }}</pre>
                            <p v-if="server.config_path" class="panel-meta">
                                config: {{ server.config_path }}
                            </p>
                            <p v-if="server.hook_path" class="panel-meta">
                                hooks: {{ server.hook_path }}
                            </p>
                            <div class="panel-actions">
                                <button
                                    v-if="server.canAutoInstall"
                                    class="action-link"
                                    type="button"
                                    data-action="install-mcp"
                                    :disabled="
                                        server.installed ||
                                        mcpInstallingId === server.id
                                    "
                                    @click="installMcpServer(server.id)"
                                >
                                    {{
                                        mcpInstallingId === server.id
                                            ? "添加中"
                                            : server.action_label
                                    }}
                                </button>
                                <button
                                    class="action-link"
                                    type="button"
                                    data-action="copy-mcp-command"
                                    @click="copyMcpCommand(server)"
                                >
                                    {{
                                        copiedMcpId === server.id
                                            ? "已复制"
                                            : "复制配置"
                                    }}
                                </button>
                            </div>
                        </article>
                    </div>
                </template>
            </template>
        </section>
    </main>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref } from "vue";
import { mockApi } from "./mockApi";

const POLL_MS = 5000;
const MAX_DIFF_LINES = 800;
const GRAPH_LIMIT = 12;

const workspacePath = ref("…");
const currentView = ref("commits");
const activeShell = ref("commits");
const currentCommitId = ref(null);
const commits = ref([]);
const agents = ref([]);
const mcpServers = ref([]);
const workspaceSummary = ref(null);
const diffRows = ref([]);
const diffLoading = ref(false);
const diffError = ref("");
const diffFlash = ref(false);
const detailLoading = ref(false);
const detailError = ref("");
const timelineError = ref("");
const statusMessage = ref("ready");
const statusTone = ref("");
const theme = ref("system");
const restoreLoadingKey = ref("");
const reassignChoice = ref("");
const reassignLoading = ref(false);
const revertLoadingAgent = ref("");
const refreshLoading = ref(false);
const mcpInstallingId = ref("");
const copiedMcpId = ref("");
let timer = null;
let stopWorkspaceListener = null;
let systemThemeQuery = null;

const api = window.api || mockApi;
const THEME_STORAGE_KEY = "trace-theme";
const HIDDEN_AGENT_NAMES = new Set([
    "cursor",
    "vscode",
    "local-script",
    "claude-script",
    "codex-script",
]);

const visibleAgents = computed(() =>
    agents.value.filter(
        (agent) =>
            !HIDDEN_AGENT_NAMES.has(
                String(agent.name || "").toLowerCase(),
            ),
    ),
);

const totalAgentCommits = computed(() =>
    visibleAgents.value.reduce(
        (sum, agent) => sum + Number(agent.commit_count || 0),
        0,
    ),
);

const activeAgentCount = computed(
    () =>
        visibleAgents.value.filter(
            (agent) => Number(agent.commit_count || 0) > 0,
        ).length,
);

const workspaceRows = computed(() => {
    const summary = workspaceSummary.value || {};
    return [
        { key: "path", value: summary.workspace ?? "—" },
        { key: "database", value: summary.db_path ?? "—" },
        { key: "commits", value: summary.commit_count ?? "—" },
        { key: "snapshots", value: summary.snapshot_count ?? "—" },
        { key: "agents", value: summary.agent_count ?? "—" },
    ];
});

const graphCommits = computed(() => {
    const recent = commits.value.slice(0, GRAPH_LIMIT).reverse();
    const count = recent.length;
    return recent.map((commit, index) => {
        const ratio = count <= 1 ? 0.5 : index / (count - 1);
        const wave = Math.sin(index * 1.7) * 18;
        return {
            ...commit,
            graphIndex: index,
            isLatest: index === count - 1,
            x: count <= 1 ? 50 : 8 + ratio * 84,
            y: 50 + wave,
        };
    });
});

const selectedCommit = computed(() =>
    commits.value.find((row) => row.id === currentCommitId.value) || null,
);

const selectedUncertainCommit = computed(() => {
    const commit = selectedCommit.value;
    return commit && isUncertain(commit) ? commit : null;
});

const reassignOptions = computed(() => {
    const commit = selectedUncertainCommit.value;
    if (!commit) return [];
    const names = candidatesOf(commit);
    if (!names.includes("human")) {
        names.push("human");
    }
    return names;
});

const graphConnections = computed(() =>
    graphCommits.value.slice(1).map((commit, index) => {
        const previous = graphCommits.value[index];
        return {
            id: `${previous.id}-${commit.id}`,
            fromId: previous.id,
            toId: commit.id,
            index,
            x1: previous.x,
            y1: previous.y,
            x2: commit.x,
            y2: commit.y,
        };
    }),
);

const mcpNeedsSetup = computed(() =>
    mcpServers.value.some(
        (server) => server.id === "codex" && !server.installed,
    ),
);

function linePrefix(tag) {
    if (tag === "added") return "+";
    if (tag === "removed") return "-";
    if (tag === "meta") return "//";
    return " ";
}

async function renderSingleDiff(filePath, prev, cur) {
    return await api.renderDiff(filePath, prev, cur);
}

async function renderDiffsForFiles(files) {
    if (files.length === 0) return new Map();
    if (typeof api.renderDiffs === "function") {
        const result = await api.renderDiffs(
            files.map((file) => ({
                file_path: file.filePath,
                prev_hash: file.prev || null,
                cur_hash: file.cur || null,
            })),
        );
        if (
            result &&
            result.ok !== false &&
            result.files &&
            typeof result.files === "object"
        ) {
            return new Map(Object.entries(result.files));
        }
        if (result && (result.error || result.ok === false)) {
            const error = result.error || "batch diff failed";
            return new Map(
                files.map((file) => [file.filePath, { ok: false, error }]),
            );
        }
    }

    const entries = [];
    for (const file of files) {
        entries.push([
            file.filePath,
            await renderSingleDiff(file.filePath, file.prev, file.cur),
        ]);
    }
    return new Map(entries);
}

async function loadWorkspace() {
    workspacePath.value = await api.getWorkspace();
}

async function loadMcpSetup() {
    if (typeof api.listMcpSetup !== "function") {
        mcpServers.value = [];
        return;
    }
    const rows = await api.listMcpSetup();
    if (rows.error) {
        throw new Error(rows.error);
    }
    mcpServers.value = Array.isArray(rows) ? rows : [];
}

async function handleWorkspaceChanged(nextWorkspace) {
    workspacePath.value = nextWorkspace;
    currentCommitId.value = null;
    diffRows.value = [];
    diffError.value = "";
    agents.value = [];
    mcpServers.value = [];
    workspaceSummary.value = null;
    setStatus("workspace 已切换，正在刷新", "ok");
    await refreshTimeline({ autoSelectLatest: true });
    await loadMcpSetup();
    if (currentView.value === "agents") {
        await showAgents();
    } else if (currentView.value === "workspace") {
        await showWorkspace();
    } else if (currentView.value === "mcp") {
        await showMcpSetup();
    }
}

async function refreshTimeline({ autoSelectLatest = false } = {}) {
    const previousTopId = commits.value[0]?.id ?? null;
    const selectedId = currentCommitId.value;
    const rows = await api.listCommits();
    if (rows.error) {
        timelineError.value = rows.error;
        setStatus("读取 commits 失败", "warn");
        return;
    }
    timelineError.value = "";
    commits.value = rows;
    const latestId = rows[0]?.id ?? null;
    if (
        autoSelectLatest &&
        latestId != null &&
        latestId !== selectedId &&
        (selectedId == null || selectedId === previousTopId)
    ) {
        await onSelectCommit(latestId);
    }
}

async function reassignSelectedCommit() {
    const commit = selectedUncertainCommit.value;
    if (!commit || !reassignChoice.value || !api.reassignCommit) {
        return;
    }
    reassignLoading.value = true;
    try {
        const result = await api.reassignCommit(
            commit.id,
            reassignChoice.value,
        );
        if (result?.error || result?.ok === false) {
            setStatus(`修正失败: ${result?.error || "unknown"}`, "warn");
            return;
        }
        setStatus(
            `commit #${commit.id} 已修正为 ${reassignChoice.value}`,
            "ok",
        );
        await refreshTimeline({ autoSelectLatest: false });
        await onSelectCommit(commit.id);
    } finally {
        reassignLoading.value = false;
    }
}

async function revertAgent(agentName) {
    if (!agentName || !api.revertAgent) {
        return;
    }
    if (!window.confirm(`确认撤销 agent "${agentName}" 的全部变更？`)) {
        return;
    }
    revertLoadingAgent.value = agentName;
    try {
        if (api.previewRevertAgent) {
            const preview = await api.previewRevertAgent(agentName);
            if (preview?.error || preview?.ok === false) {
                setStatus(`预览失败: ${preview?.error || "unknown"}`, "warn");
                return;
            }
            const count = Array.isArray(preview.changed_paths)
                ? preview.changed_paths.length
                : 0;
            if (
                count > 0 &&
                !window.confirm(
                    `将影响 ${count} 个文件。继续撤销 ${agentName} 的全部变更？`,
                )
            ) {
                return;
            }
        }
        const result = await api.revertAgent(agentName);
        if (result?.error || result?.ok === false) {
            setStatus(`撤销失败: ${result?.error || "unknown"}`, "warn");
            return;
        }
        setStatus(
            `已撤销 ${agentName}，新 commit #${result.commit_id}`,
            "ok",
        );
        await refreshTimeline({ autoSelectLatest: true });
        await loadAgents();
    } finally {
        revertLoadingAgent.value = "";
    }
}

async function onSelectCommit(commitId) {
    currentView.value = "commits";
    currentCommitId.value = commitId;
    const commit = commits.value.find((row) => row.id === commitId);
    if (commit && isUncertain(commit)) {
        const options = candidatesOf(commit);
        reassignChoice.value = options[0] || "human";
    }
    diffLoading.value = true;
    diffError.value = "";
    diffRows.value = [];

    try {
        const prevId = await api.getPrevCommitId(commitId);
        const curManifest = await api.getManifest(commitId);
        const prevManifest = prevId ? await api.getManifest(prevId) : [];

        const curMap = new Map(
            curManifest.map((row) => [row.file_path, row.blob_hash]),
        );
        const prevMap = new Map(
            prevManifest.map((row) => [row.file_path, row.blob_hash]),
        );
        const sorted = Array.from(
            new Set([...curMap.keys(), ...prevMap.keys()]),
        ).sort();
        const rows = [];
        const changedFiles = [];

        for (const filePath of sorted) {
            const cur = curMap.get(filePath);
            const prev = prevMap.get(filePath);
            if (cur === prev) continue;

            let status = "[修改]";
            let statusClass = "mod";
            if (prev == null) {
                status = "[新增]";
                statusClass = "new";
            } else if (cur == null) {
                status = "[删除]";
                statusClass = "del";
            }
            changedFiles.push({ filePath, prev, cur, status, statusClass });
        }

        const diffResults = await renderDiffsForFiles(changedFiles);
        for (const file of changedFiles) {
            rows.push({
                type: "file",
                status: file.status,
                statusClass: file.statusClass,
                path: file.filePath,
                commitId,
                canRestore: file.cur != null,
            });

            const diff = diffResults.get(file.filePath);
            if (!diff || diff.error || diff.ok === false) {
                rows.push({
                    type: "line",
                    tag: "meta",
                    prefix: "//",
                    text: `diff handler 失败: ${diff?.error || "unknown error"}`,
                });
                continue;
            }
            const lines = Array.isArray(diff.lines) ? diff.lines : [];
            const trimmed =
                lines.length > MAX_DIFF_LINES
                    ? lines
                          .slice(0, MAX_DIFF_LINES)
                          .concat([
                              {
                                  tag: "meta",
                                  text: `... (省略 ${lines.length - MAX_DIFF_LINES} 行)`,
                              },
                          ])
                    : lines;
            for (const line of trimmed) {
                const tag = line.tag || "normal";
                rows.push({
                    type: "line",
                    tag,
                    prefix: linePrefix(tag),
                    text: line.text || "",
                });
            }
        }

        if (rows.length === 0) {
            rows.push({
                type: "line",
                tag: "meta",
                prefix: "//",
                text:
                    prevId == null
                        ? "这次 commit 没有文件变化"
                        : "这次 commit 和上一条快照完全一致；如果你在找新增内容，请点前一条真正发生变化的 commit",
            });
        }
        diffRows.value = rows;
        setStatus(`commit #${commitId} diff 已加载`, "ok");
    } catch (e) {
        diffError.value = String(e);
        setStatus("diff 渲染失败", "warn");
    } finally {
        diffLoading.value = false;
    }
}

async function showCommits() {
    currentView.value = "commits";
    activeShell.value = "commits";
    setStatus("显示 commit 时间线", "ok");
}

async function showAgents() {
    currentView.value = "agents";
    activeShell.value = "agents";
    detailLoading.value = true;
    detailError.value = "";

    try {
        const rows = await api.listAgents();
        if (rows.error) throw new Error(rows.error);
        agents.value = rows;
        setStatus("agent 面板已更新", "ok");
    } catch (e) {
        detailError.value = String(e);
        setStatus("agent 面板加载失败", "warn");
    } finally {
        detailLoading.value = false;
    }
}

async function showWorkspace() {
    currentView.value = "workspace";
    activeShell.value = "workspace";
    detailLoading.value = true;
    detailError.value = "";

    try {
        const summary = await api.getWorkspaceSummary();
        if (summary.error) throw new Error(summary.error);
        workspaceSummary.value = summary;
        setStatus("workspace 面板已更新", "ok");
    } catch (e) {
        detailError.value = String(e);
        setStatus("workspace 面板加载失败", "warn");
    } finally {
        detailLoading.value = false;
    }
}

async function showMcpSetup() {
    currentView.value = "mcp";
    activeShell.value = "mcp";
    detailLoading.value = true;
    detailError.value = "";

    try {
        await loadMcpSetup();
        setStatus("MCP 设置已更新", "ok");
    } catch (e) {
        detailError.value = String(e);
        setStatus("MCP 设置加载失败", "warn");
    } finally {
        detailLoading.value = false;
    }
}

async function showDiff() {
    await showCommits();
    if (currentCommitId.value == null && commits.value.length > 0) {
        await onSelectCommit(commits.value[0].id);
    }
    activeShell.value = "diff";
    diffFlash.value = false;
    await nextTick();
    diffFlash.value = true;
    window.setTimeout(() => {
        diffFlash.value = false;
    }, 750);
    setStatus(
        currentCommitId.value == null
            ? "请选择左侧 commit 查看 diff"
            : "diff 面板已聚焦",
        "ok",
    );
}

async function openGithub() {
    try {
        const result = await api.openGithub();
        if (result && result.error) throw new Error(result.error);
        setStatus(`已打开 GitHub: ${result.url}`, "ok");
    } catch (e) {
        setStatus(`打开 GitHub 失败: ${String(e)}`, "warn");
    }
}

async function manualRefresh() {
    refreshLoading.value = true;
    try {
        await refreshTimeline({ autoSelectLatest: true });
        if (currentView.value === "agents") {
            await showAgents();
        } else if (currentView.value === "workspace") {
            await showWorkspace();
        } else if (currentView.value === "mcp") {
            await showMcpSetup();
        } else {
            await loadMcpSetup();
        }
        setStatus("已刷新最新记录", "ok");
    } catch (e) {
        setStatus(`刷新失败: ${String(e)}`, "warn");
    } finally {
        refreshLoading.value = false;
    }
}

async function installMcpServer(serverId) {
    if (!serverId || typeof api.installMcpServer !== "function") {
        return;
    }
    mcpInstallingId.value = serverId;
    try {
        const result = await api.installMcpServer(serverId);
        if (result?.error || result?.ok === false) {
            setStatus(`MCP 添加失败: ${result?.error || "unknown"}`, "warn");
            return;
        }
        await loadMcpSetup();
        if (serverId === "codex") {
            setStatus(
                result.already_installed
                    ? "Trace MCP 与 hooks 已经配置"
                    : "Trace MCP 与 hooks 已添加；重启 Codex 后在 /hooks 信任一次",
                "ok",
            );
        } else if (serverId === "claude") {
            setStatus(
                result.already_installed
                    ? "Claude Trace MCP 已经配置"
                    : "Claude Trace MCP 已添加；重启 Claude 后批准一次",
                "ok",
            );
        } else if (serverId === "opencode") {
            setStatus(
                result.already_installed
                    ? "OpenCode Trace MCP 已经配置"
                    : "OpenCode Trace MCP 已添加；重启 OpenCode 后生效",
                "ok",
            );
        } else {
            setStatus("Trace MCP 已添加", "ok");
        }
    } catch (e) {
        setStatus(`MCP 添加失败: ${String(e)}`, "warn");
    } finally {
        mcpInstallingId.value = "";
    }
}

async function copyMcpCommand(server) {
    if (!server?.command) return;
    try {
        await window.navigator?.clipboard?.writeText(server.command);
        copiedMcpId.value = server.id;
        window.setTimeout(() => {
            if (copiedMcpId.value === server.id) copiedMcpId.value = "";
        }, 1400);
        setStatus(`${server.name} MCP 配置已复制`, "ok");
    } catch (e) {
        setStatus(`复制 MCP 配置失败: ${String(e)}`, "warn");
    }
}

async function restoreFile(commitId, filePath) {
    const key = fileKey(commitId, filePath);
    restoreLoadingKey.value = key;
    try {
        const result = await api.restoreFile(commitId, filePath);
        if (!result || result.error || result.ok === false) {
            throw new Error(result?.error || "restore failed");
        }
        const backupNote =
            result.backup_id == null
                ? "无新备份"
                : `已备份为 commit #${result.backup_id}`;
        setStatus(
            `已回滚 ${filePath} 到 commit #${commitId}，${backupNote}`,
            "ok",
        );
        await refreshTimeline({ autoSelectLatest: false });
        await onSelectCommit(commitId);
    } catch (e) {
        setStatus(`回滚失败: ${String(e)}`, "warn");
    } finally {
        restoreLoadingKey.value = "";
    }
}

function setStatus(message, tone = "") {
    statusMessage.value = message;
    statusTone.value = tone;
}

function resolveTheme(nextTheme = theme.value) {
    if (nextTheme === "system") {
        return systemThemeQuery?.matches ? "dark" : "light";
    }
    return nextTheme === "light" ? "light" : "dark";
}

function applyTheme() {
    document.documentElement.dataset.theme = resolveTheme();
}

function setTheme(nextTheme) {
    theme.value = ["system", "light", "dark"].includes(nextTheme)
        ? nextTheme
        : "system";
    applyTheme();
    window.localStorage?.setItem(THEME_STORAGE_KEY, theme.value);
}

function fileKey(commitId, filePath) {
    return `${commitId}:${filePath}`;
}

function graphNodeStyle(commit) {
    return {
        "--node-x": `${commit.x}%`,
        "--node-y": `${commit.y}%`,
        "--node-delay": `${commit.graphIndex * 70}ms`,
    };
}

function formatTime(value) {
    return String(value || "")
        .replace("T", " ")
        .slice(0, 19);
}

function formatLast(value) {
    return value ? formatTime(value) : "never";
}

function candidatesOf(commit) {
    return Array.isArray(commit?.candidates)
        ? commit.candidates.filter(Boolean)
        : [];
}

function isUncertain(commit) {
    return Boolean(
        commit?.author_agent === "unknown" && candidatesOf(commit).length > 0,
    );
}

function agentLabel(commit) {
    if (isUncertain(commit)) {
        return `? ${candidatesOf(commit).join("/")}`;
    }
    return commit?.author_agent || "unknown";
}

function agentTitle(commit) {
    if (!isUncertain(commit)) {
        return `agent: ${commit?.author_agent || "unknown"}`;
    }
    return `低置信度候选: ${candidatesOf(commit).join(", ")}`;
}

function agentClass(value) {
    return (
        String(value || "unknown")
            .toLowerCase()
            .replace(/[^a-z0-9_-]+/g, "-")
            .replace(/^-+|-+$/g, "") || "unknown"
    );
}

onMounted(async () => {
    systemThemeQuery =
        window.matchMedia?.("(prefers-color-scheme: dark)") || null;
    systemThemeQuery?.addEventListener?.("change", applyTheme);
    const savedTheme = window.localStorage?.getItem(THEME_STORAGE_KEY);
    setTheme(
        ["system", "light", "dark"].includes(savedTheme)
            ? savedTheme
            : "system",
    );
    await loadWorkspace();
    await loadMcpSetup();
    await refreshTimeline({ autoSelectLatest: true });
    if (api.onWorkspaceChanged) {
        stopWorkspaceListener = api.onWorkspaceChanged(handleWorkspaceChanged);
    }
    const schedulePoll = () => {
        if (timer != null) {
            window.clearInterval(timer);
            timer = null;
        }
        if (document.visibilityState === "hidden") {
            return;
        }
        timer = window.setInterval(
            () => refreshTimeline({ autoSelectLatest: true }),
            POLL_MS,
        );
    };
    document.addEventListener("visibilitychange", schedulePoll);
    schedulePoll();
});

onUnmounted(() => {
    if (timer != null) {
        window.clearInterval(timer);
    }
    if (stopWorkspaceListener) {
        stopWorkspaceListener();
    }
    systemThemeQuery?.removeEventListener?.("change", applyTheme);
});
</script>
