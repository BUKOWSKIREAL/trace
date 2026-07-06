#!/usr/bin/env bash
# Source install fallback for environments where py2app or create-dmg is not
# available. It prepares Python and Electron dependencies and creates a
# double-clickable launcher in dist/.

set -euo pipefail

cd "$(dirname "$0")"

if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv is required. Install uv and rerun ./install.sh."
    exit 1
fi

echo "=== Trace source install fallback ==="
echo "[1/3] Sync Python dependencies"
uv sync

if command -v npm >/dev/null 2>&1; then
    echo "[2/3] Install Electron console dependencies"
    (cd electron_app && npm install)
else
    echo "[2/3] npm not found; Tk console and headless CLI still work"
fi

echo "[3/3] Write launcher"
mkdir -p dist
cat > dist/Trace.command <<'LAUNCHER'
#!/usr/bin/env bash
cd "$(dirname "$0")/.."
exec uv run python code/main.py "$@"
LAUNCHER
chmod +x dist/Trace.command

echo
echo "Installed source launcher: dist/Trace.command"
echo "CLI alternative: uv run python code/main.py --workspace test_workspace"
