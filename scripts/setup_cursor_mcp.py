#!/usr/bin/env python
"""
Cursor MCP 配置助手

自动为 Cursor 配置 Trace MCP 服务器。
支持 macOS、Linux 和 Windows。
"""

import json
import os
import platform
import sys
from pathlib import Path


def get_cursor_config_path() -> Path:
    """获取 Cursor 的 MCP 配置文件路径"""
    system = platform.system()

    if system == "Darwin":  # macOS
        return Path.home() / "Library/Application Support/Cursor/User/mcp.json"
    elif system == "Linux":
        return Path.home() / ".config/Cursor/User/mcp.json"
    elif system == "Windows":
        appdata = Path(os.environ.get("APPDATA", ""))
        return appdata / "Cursor/User/mcp.json"
    else:
        raise RuntimeError(f"不支持的操作系统: {system}")


def get_project_root() -> Path:
    """获取项目根目录"""
    return Path(__file__).resolve().parent.parent


def get_python_command() -> str:
    """Return a Python launcher that works well for Cursor MCP stdio."""
    if platform.system() == "Windows":
        return "py"
    return sys.executable or "python"


def load_or_create_config(config_path: Path) -> dict:
    """加载现有配置或创建新配置"""
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            print(f"⚠️  警告: 配置文件格式错误，将备份并创建新配置")
            backup_path = config_path.with_suffix(".json.backup")
            config_path.rename(backup_path)
            print(f"   已备份到: {backup_path}")

    return {"mcpServers": {}}


def setup_trace_mcp(workspace_path: Path | None = None, auto_confirm: bool = False):
    """配置 Trace MCP 服务器"""
    project_root = get_project_root()
    config_path = get_cursor_config_path()

    print("=" * 60)
    print("Cursor MCP 配置助手 - Trace")
    print("=" * 60)
    print()
    print(f"项目根目录: {project_root}")
    print(f"配置文件路径: {config_path}")
    print()

    # 确定工作区路径
    if workspace_path is None:
        default_workspace = project_root
        workspace_input = input(f"请输入工作区路径 (默认: {default_workspace}): ").strip()
        workspace_path = Path(workspace_input) if workspace_input else default_workspace

    workspace_path = workspace_path.expanduser().resolve()
    if not workspace_path.exists():
        raise FileNotFoundError(f"工作区不存在: {workspace_path}")
    print(f"工作区路径: {workspace_path}")
    print()

    # 加载现有配置
    config = load_or_create_config(config_path)

    # 检查是否已存在 trace 配置
    if "trace" in config.get("mcpServers", {}):
        print("⚠️  检测到已存在的 Trace MCP 配置:")
        print(json.dumps(config["mcpServers"]["trace"], indent=2))
        print()
        if not auto_confirm:
            overwrite = input("是否覆盖? (y/N): ").strip().lower()
            if overwrite != "y":
                print("已取消")
                return

    # 创建新配置
    trace_config = {
        "type": "stdio",
        "command": get_python_command(),
        "args": [
            str(project_root / "run_mcp_server.py"),
            "--workspace",
            str(workspace_path)
        ]
    }

    config.setdefault("mcpServers", {})["trace"] = trace_config

    # 确保配置目录存在
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # 写入配置
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    print("✅ 配置已成功写入!")
    print()
    print("完整配置:")
    print(json.dumps(trace_config, indent=2))
    print()
    print("下一步:")
    print("1. 重启 Cursor")
    print("2. 在 Cursor 中验证 MCP 工具是否可用")
    print("3. 使用 trace_record_files 工具报告文件变更")
    print()
    print("示例调用:")
    print('  trace_record_files(agent="cursor", files=["src/main.py"], operation="write")')
    print()


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="为 Cursor 配置 Trace MCP 服务器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 交互式配置
  python scripts/setup_cursor_mcp.py

  # 指定工作区路径
  python scripts/setup_cursor_mcp.py --workspace /path/to/workspace

  # 自动确认（非交互式）
  python scripts/setup_cursor_mcp.py --workspace . --auto-confirm
        """
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        help="工作区路径（默认: 项目根目录）"
    )
    parser.add_argument(
        "--auto-confirm",
        action="store_true",
        help="自动确认，不询问（用于脚本自动化）"
    )

    args = parser.parse_args()

    try:
        setup_trace_mcp(args.workspace, args.auto_confirm)
    except KeyboardInterrupt:
        print("\n已取消")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
