#!/bin/bash
# Start the Trace MCP server with proper PYTHONPATH
# Usage: ./scripts/start_mcp_server.sh [--workspace PATH]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CODE_DIR="$PROJECT_ROOT/code"
VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"

# Set PYTHONPATH to include the code directory
export PYTHONPATH="$CODE_DIR:${PYTHONPATH}"

# Default workspace is the project root
WORKSPACE="$PROJECT_ROOT"

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --workspace)
      WORKSPACE="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

# Run the MCP server
if [[ -x "$VENV_PYTHON" ]]; then
  PYTHON_BIN="$VENV_PYTHON"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  PYTHON_BIN="$(command -v python)"
fi

exec "$PYTHON_BIN" -m mcp.trace_server --workspace "$WORKSPACE"
