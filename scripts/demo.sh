#!/usr/bin/env bash
# scripts/demo.sh — 一键演示 Trace
#
# 流程：
#   1. 重建 test_workspace 的 .trace 目录
#   2. 启 daemon（headless 模式，避免占用 TUI）
#   3. 模拟一段文件变化序列
#   4. 退出 daemon，确认 .trace/trace.db 有 commit
#   5. 提示用户启动 Textual TUI 查看时间线和 diff
#
# 用法：bash scripts/demo.sh

set -euo pipefail

cd "$(dirname "$0")/.."

WORKSPACE="test_workspace"
mkdir -p "$WORKSPACE"

if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv is required. Install uv and rerun this script."
    exit 1
fi

# 清掉旧数据库（演示要“从空到有”的可视过程）
rm -rf "$WORKSPACE/.trace"

echo "=== Trace Demo ==="
echo "workspace: $(pwd)/$WORKSPACE"
echo

echo "[1/4] 启动 daemon（headless 模式）..."
uv run python code/main.py --workspace "$WORKSPACE" --headless > /tmp/trace_demo.log 2>&1 &
DPID=$!
cleanup() {
    if kill -0 "$DPID" 2>/dev/null; then
        kill -INT "$DPID" 2>/dev/null || true
        wait "$DPID" 2>/dev/null || true
    fi
}
trap cleanup EXIT
sleep 2

if ! kill -0 "$DPID" 2>/dev/null; then
    echo "ERROR: daemon 启动失败"
    cat /tmp/trace_demo.log
    exit 1
fi
echo "    daemon PID = $DPID"
echo

echo "[2/4] 模拟改文件序列..."
echo "print('hello')" > "$WORKSPACE/demo.py"
echo "    + demo.py (创建)"
sleep 3

echo "print('hello, world')" > "$WORKSPACE/demo.py"
echo "    ~ demo.py (修改)"
sleep 3

mkdir -p "$WORKSPACE/docs"
cat > "$WORKSPACE/docs/notes.md" <<'NOTES_EOF'
# Demo Notes

Trace 自动追踪了所有这些改动。

- 创建文件
- 修改文件
- 跨目录组织
NOTES_EOF
echo "    + docs/notes.md (新建多级目录)"
sleep 3

rm "$WORKSPACE/demo.py"
echo "    - demo.py (删除)"
sleep 3

echo
echo "[3/4] 停 daemon..."
kill -INT "$DPID" 2>/dev/null
wait "$DPID" 2>/dev/null || true
trap - EXIT
sleep 1

echo
echo "[4/4] 验证 SQLite：commit 应当真的落库了"
echo
uv run python - <<'PY'
import sqlite3
from pathlib import Path

db = Path("test_workspace/.trace/trace.db")
conn = sqlite3.connect(db)
try:
    rows = conn.execute(
        "SELECT id, time, author_agent, summary FROM commits ORDER BY id"
    ).fetchall()
finally:
    conn.close()

print("id | time | author_agent | summary")
print("---|------|--------------|--------")
for row in rows:
    print(" | ".join(str(value) for value in row))
PY

echo
echo "=== 数据已就绪。启动 TUI 查看时间线和 diff ==="
echo
echo "  uv run python code/main.py --workspace $WORKSPACE"
echo
echo "或仅运行后台守护进程："
echo
echo "  uv run python code/main.py --workspace $WORKSPACE --headless"
echo
