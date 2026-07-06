// preload.js — context bridge 把 Main 进程的 ipc 暴露给 renderer
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("api", {
  listCommits: () => ipcRenderer.invoke("list-commits"),
  getManifest: (commitId) => ipcRenderer.invoke("get-manifest", commitId),
  getPrevCommitId: (commitId) =>
    ipcRenderer.invoke("get-prev-commit-id", commitId),
  renderDiff: (filePath, prevHash, curHash) =>
    ipcRenderer.invoke("render-diff", filePath, prevHash, curHash),
  renderDiffs: (files) => ipcRenderer.invoke("render-diffs", files),
  restoreFile: (commitId, filePath) =>
    ipcRenderer.invoke("restore-file", commitId, filePath),
  reassignCommit: (commitId, newAgent) =>
    ipcRenderer.invoke("reassign-commit", commitId, newAgent),
  previewRevertAgent: (agent) =>
    ipcRenderer.invoke("preview-revert-agent", agent),
  revertAgent: (agent) => ipcRenderer.invoke("revert-agent", agent),
  getWorkspace: () => ipcRenderer.invoke("get-workspace"),
  listAgents: () => ipcRenderer.invoke("list-agents"),
  getWorkspaceSummary: () => ipcRenderer.invoke("get-workspace-summary"),
  listMcpSetup: () => ipcRenderer.invoke("list-mcp-setup"),
  installMcpServer: (serverId) => ipcRenderer.invoke("install-mcp-server", serverId),
  openGithub: () => ipcRenderer.invoke("open-github"),
  onWorkspaceChanged: (callback) => {
    const handler = (_event, workspace) => callback(workspace);
    ipcRenderer.on("workspace-changed", handler);
    return () => ipcRenderer.removeListener("workspace-changed", handler);
  },
});
