"""
Frozen executable entrypoint for Electron's Python bridge.

PyInstaller builds this file as TraceBridge.exe on Windows. Electron passes the
target bridge module name as argv[1], and this entrypoint dispatches to that
module's main() while keeping the supported surface small and explicit.
"""
from __future__ import annotations

import importlib
import os
import sys


_ALLOWED_MODULES = {
    "core.electron_diff_bridge",
    "core.electron_restore_bridge",
    "core.electron_init_bridge",
    "core.electron_reassign_bridge",
    "core.electron_revert_agent_bridge",
    "hooks.trace_codex_hook",
    "mcp.trace_server",
}


def main() -> int:
    module_name = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("TRACE_PYTHON_MODULE", "")
    if module_name not in _ALLOWED_MODULES:
        sys.stderr.write(f"unsupported bridge module: {module_name}\n")
        return 2
    module = importlib.import_module(module_name)
    argv = sys.argv[2:] if len(sys.argv) > 1 else None
    if module_name in {"hooks.trace_codex_hook", "mcp.trace_server"}:
        result = module.main(argv)
    else:
        result = module.main()
    return int(result or 0)


if __name__ == "__main__":
    raise SystemExit(main())
