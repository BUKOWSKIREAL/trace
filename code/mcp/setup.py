"""MCP setup helpers for the Textual TUI.

Detects and installs Trace MCP configuration for Codex, Claude Code and OpenCode.
The TUI view layer talks to this module through ``TraceController``; it never
touches the filesystem directly.

Trace is a pure-Python product, so the launch spec is
``sys.executable -m mcp.trace_server --workspace <ws>`` with ``PYTHONPATH``
pointing at the project's ``code/`` directory.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

TRACE_MCP_MODULE = "mcp.trace_server"
TRACE_CODEX_HOOK_MODULE = "hooks.trace_codex_hook"
TRACE_MCP_TOOL = "trace_record_files"
TRACE_MCP_SERVER_NAME = "trace"
CODEX_MCP_ADD_PREFIX = "codex mcp add"
CLAUDE_MCP_ADD_PREFIX = "claude mcp add"
OPENCODE_MCP_ADD_PREFIX = "opencode mcp add"

_PRE_MATCHER = "apply_patch|Edit|Write|MultiEdit"
_POST_MATCHER = "Bash|Shell|exec_command|apply_patch|Edit|Write|MultiEdit"


def _shell_quote(value: Any) -> str:
    text = str(value)
    if re.fullmatch(r"[A-Za-z0-9_/:=.,@%+\-]+", text):
        return text
    return "'" + text.replace("'", "'\\''") + "'"


def _command_line(argv: list[Any]) -> str:
    return " ".join(_shell_quote(arg) for arg in argv)


def _path_in_text(text: str, target_path: Path) -> bool:
    normalized = str(target_path or "")
    if not normalized:
        return False
    candidates = {
        normalized,
        normalized.replace("\\", "/"),
        normalized.replace("\\", "\\\\"),
    }
    return any(candidate and candidate in str(text) for candidate in candidates)


def _format_toml_value(value: Any) -> str:
    return json.dumps(str(value))


def _format_toml_array(values: list[Any]) -> str:
    return "[" + ", ".join(_format_toml_value(v) for v in values) + "]"


def _extract_toml_section(text: str, section_name: str) -> str:
    marker = f"[{section_name}]"
    section: list[str] = []
    active = False
    for line in str(text or "").splitlines():
        trimmed = line.strip()
        if re.match(r"^\[[^\]]+\]$", trimmed):
            if trimmed == marker:
                active = True
                section.append(line)
                continue
            if active:
                break
        elif active:
            section.append(line)
    return "\n".join(section)


def _strip_toml_sections(text: str, section_names: list[str]) -> str:
    names = set(section_names)
    kept: list[str] = []
    skip = False
    for line in str(text or "").splitlines():
        trimmed = line.strip()
        match = re.match(r"^\[([^\]]+)\]$", trimmed)
        if match:
            skip = match.group(1) in names
        if not skip:
            kept.append(line)
    return "\n".join(kept).rstrip()


def _strip_json_comments(text: str) -> str:
    out: list[str] = []
    in_string = False
    escaped = False
    in_line_comment = False
    in_block_comment = False
    chars = list(str(text))
    i = 0
    while i < len(chars):
        char = chars[i]
        nxt = chars[i + 1] if i + 1 < len(chars) else ""
        if in_line_comment:
            if char in "\r\n":
                in_line_comment = False
                out.append(char)
            i += 1
            continue
        if in_block_comment:
            if char == "*" and nxt == "/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue
        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            i += 1
            continue
        if char == '"':
            in_string = True
            out.append(char)
            i += 1
            continue
        if char == "/" and nxt == "/":
            in_line_comment = True
            i += 2
            continue
        if char == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue
        out.append(char)
        i += 1
    return "".join(out)


def _strip_trailing_json_commas(text: str) -> str:
    out: list[str] = []
    in_string = False
    escaped = False
    chars = list(str(text))
    i = 0
    while i < len(chars):
        char = chars[i]
        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            i += 1
            continue
        if char == '"':
            in_string = True
            out.append(char)
            i += 1
            continue
        if char == ",":
            j = i + 1
            while j < len(chars) and chars[j].isspace():
                j += 1
            if j < len(chars) and chars[j] in "}]":
                i += 1
                continue
        out.append(char)
        i += 1
    return "".join(out)


def _parse_json_like_object(text: str) -> dict:
    try:
        parsed = json.loads(_strip_trailing_json_commas(_strip_json_comments(text)))
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _load_json_object(path: Path) -> dict:
    try:
        return _parse_json_like_object(path.read_text(encoding="utf-8"))
    except OSError:
        return {}


class McpSetup:
    """Detects and installs Trace MCP for Codex / Claude / OpenCode."""

    def __init__(self, workspace: Path, home: Path | None = None) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.home = Path(home).expanduser() if home else Path.home()
        self.project_root = Path(__file__).resolve().parents[2]

    # --- paths -------------------------------------------------------------

    def _codex_config_path(self) -> Path:
        return self.home / ".codex" / "config.toml"

    def _codex_hooks_path(self) -> Path:
        return self.home / ".codex" / "hooks.json"

    def _opencode_config_path(self) -> Path:
        return self.home / ".config" / "opencode" / "opencode.jsonc"

    def _claude_user_config_path(self) -> Path:
        return self.home / ".claude.json"

    def _claude_workspace_config_path(self) -> Path:
        return self.workspace / ".mcp.json"

    # --- launch specs ------------------------------------------------------

    def _launch_spec(self) -> dict[str, Any]:
        return {
            "command": sys.executable,
            "args": ["-m", TRACE_MCP_MODULE, "--workspace", str(self.workspace)],
            "cwd": str(self.project_root),
            "env": {"PYTHONPATH": str(self.project_root / "code")},
        }

    def _hook_launch_spec(self, phase: str) -> dict[str, Any]:
        spec = self._launch_spec()
        return {
            "command": spec["command"],
            "args": [
                "-m",
                TRACE_CODEX_HOOK_MODULE,
                "--workspace",
                str(self.workspace),
                "--phase",
                phase,
            ],
            "cwd": spec["cwd"],
            "env": spec["env"],
        }

    def _trace_mcp_config_object(self) -> dict[str, Any]:
        spec = self._launch_spec()
        config: dict[str, Any] = {
            "type": "local",
            "command": [spec["command"], *spec["args"]],
            "enabled": True,
        }
        if spec["env"]:
            config["environment"] = spec["env"]
        return config

    # --- codex MCP / hooks -------------------------------------------------

    def _inspect_codex_mcp(self) -> dict[str, Any]:
        config_path = self._codex_config_path()
        try:
            text = config_path.read_text(encoding="utf-8")
        except OSError:
            text = ""
        section = _extract_toml_section(text, f"mcp_servers.{TRACE_MCP_SERVER_NAME}")
        has_trace_section = bool(section)
        has_trace_server = TRACE_MCP_MODULE in section
        has_workspace = _path_in_text(section, self.workspace)
        return {
            "config_path": str(config_path),
            "has_trace_section": has_trace_section,
            "has_trace_server": has_trace_server,
            "has_workspace": has_workspace,
            "installed": has_trace_section and has_trace_server and has_workspace,
        }

    def _install_codex_mcp_config(self) -> dict[str, Any]:
        config_path = self._codex_config_path()
        try:
            existing = config_path.read_text(encoding="utf-8")
        except OSError:
            existing = ""
        cleaned = _strip_toml_sections(
            existing,
            [
                f"mcp_servers.{TRACE_MCP_SERVER_NAME}",
                f"mcp_servers.{TRACE_MCP_SERVER_NAME}.env",
            ],
        )
        spec = self._launch_spec()
        lines = [
            f"[mcp_servers.{TRACE_MCP_SERVER_NAME}]",
            f"command = {_format_toml_value(spec['command'])}",
            f"args = {_format_toml_array(spec['args'])}",
        ]
        env_entries = list((spec.get("env") or {}).items())
        if env_entries:
            lines.append("")
            lines.append(f"[mcp_servers.{TRACE_MCP_SERVER_NAME}.env]")
            for key, value in env_entries:
                lines.append(f"{key} = {_format_toml_value(value)}")
        new_section = "\n".join(lines)
        parts = [p for p in (cleaned, new_section) if p.strip()]
        next_text = "\n\n".join(parts) + "\n"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(next_text, encoding="utf-8")
        return self._inspect_codex_mcp()

    def _load_codex_hooks_config(self) -> dict[str, Any]:
        try:
            return json.loads(self._codex_hooks_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"hooks": {}}

    def _is_trace_hook_entry(self, entry: Any) -> bool:
        if not isinstance(entry, dict):
            return False
        hooks = entry.get("hooks")
        if not isinstance(hooks, list):
            return False
        return any(
            TRACE_CODEX_HOOK_MODULE in str(h.get("command", ""))
            for h in hooks
            if isinstance(h, dict)
        )

    def _strip_trace_hook_entries(self, entries: Any) -> list[Any]:
        if not isinstance(entries, list):
            return []
        return [e for e in entries if not self._is_trace_hook_entry(e)]

    def _hook_command(self, phase: str) -> str:
        spec = self._hook_launch_spec(phase)
        env_prefix = " ".join(
            f"{k}={_shell_quote(v)}" for k, v in (spec.get("env") or {}).items()
        )
        prefix = f"{env_prefix} " if env_prefix else ""
        return f"{prefix}{_command_line([spec['command'], *spec['args']])}"

    def _trace_hook_entry(self, phase: str) -> dict[str, Any]:
        matcher = _PRE_MATCHER if phase == "pre" else _POST_MATCHER
        return {
            "matcher": matcher,
            "hooks": [
                {
                    "type": "command",
                    "command": self._hook_command(phase),
                    "timeout": 5,
                    "statusMessage": (
                        "Trace records Codex write intent"
                        if phase == "pre"
                        else "Trace records Codex file changes"
                    ),
                }
            ],
        }

    def _inspect_codex_hook(self) -> dict[str, Any]:
        hooks_path = self._codex_hooks_path()
        config = self._load_codex_hooks_config()
        hooks = config.get("hooks") if isinstance(config.get("hooks"), dict) else {}
        all_entries: list[Any] = []
        if isinstance(hooks.get("PreToolUse"), list):
            all_entries.extend(hooks["PreToolUse"])
        if isinstance(hooks.get("PostToolUse"), list):
            all_entries.extend(hooks["PostToolUse"])
        has_trace_hook = any(self._is_trace_hook_entry(e) for e in all_entries)
        serialized = json.dumps(all_entries)
        has_workspace = _path_in_text(serialized, self.workspace)
        return {
            "hooks_path": str(hooks_path),
            "has_trace_hook": has_trace_hook,
            "has_workspace": has_workspace,
            "installed": has_trace_hook and has_workspace,
        }

    def _install_codex_hook_config(self) -> dict[str, Any]:
        hooks_path = self._codex_hooks_path()
        config = self._load_codex_hooks_config()
        hooks = config.get("hooks") if isinstance(config.get("hooks"), dict) else {}
        pre = (
            hooks.get("PreToolUse") if isinstance(hooks.get("PreToolUse"), list) else []
        )
        post = (
            hooks.get("PostToolUse")
            if isinstance(hooks.get("PostToolUse"), list)
            else []
        )
        hooks["PreToolUse"] = [
            *self._strip_trace_hook_entries(pre),
            self._trace_hook_entry("pre"),
        ]
        hooks["PostToolUse"] = [
            *self._strip_trace_hook_entries(post),
            self._trace_hook_entry("post"),
        ]
        config["hooks"] = hooks
        hooks_path.parent.mkdir(parents=True, exist_ok=True)
        hooks_path.write_text(
            json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        return self._inspect_codex_hook()

    # --- claude ------------------------------------------------------------

    def _inspect_claude_mcp(self) -> dict[str, Any]:
        config_paths = [
            self._claude_user_config_path(),
            self._claude_workspace_config_path(),
        ]
        texts: list[str] = []
        for config_path in config_paths:
            try:
                texts.append(config_path.read_text(encoding="utf-8"))
            except OSError:
                texts.append("")
        serialized = "\n".join(texts)
        installed = TRACE_MCP_MODULE in serialized and _path_in_text(
            serialized, self.workspace
        )
        user_text = texts[0]
        config_path = (
            config_paths[0]
            if (installed and TRACE_MCP_MODULE in user_text)
            else config_paths[1]
        )
        return {
            "config_path": str(config_path),
            "has_trace_section": f'"{TRACE_MCP_SERVER_NAME}"' in serialized,
            "has_trace_server": TRACE_MCP_MODULE in serialized,
            "has_workspace": _path_in_text(serialized, self.workspace),
            "installed": installed,
        }

    # --- opencode ----------------------------------------------------------

    def _inspect_opencode_mcp(self) -> dict[str, Any]:
        config_path = self._opencode_config_path()
        config = _load_json_object(config_path)
        mcp = config.get("mcp") if isinstance(config.get("mcp"), dict) else {}
        trace = (
            mcp.get(TRACE_MCP_SERVER_NAME)
            if isinstance(mcp.get(TRACE_MCP_SERVER_NAME), dict)
            else {}
        )
        serialized = json.dumps(trace or {})
        return {
            "config_path": str(config_path),
            "has_trace_section": bool(trace),
            "has_trace_server": TRACE_MCP_MODULE in serialized,
            "has_workspace": _path_in_text(serialized, self.workspace),
            "installed": TRACE_MCP_MODULE in serialized
            and _path_in_text(serialized, self.workspace),
        }

    def _install_opencode_config(self) -> dict[str, Any]:
        config_path = self._opencode_config_path()
        config = _load_json_object(config_path)
        mcp = config.get("mcp") if isinstance(config.get("mcp"), dict) else {}
        mcp[TRACE_MCP_SERVER_NAME] = self._trace_mcp_config_object()
        config["mcp"] = mcp
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        return self._inspect_opencode_mcp()

    # --- command builders --------------------------------------------------

    def _find_binary(self, env_var: str, name: str) -> str:
        env_path = os.environ.get(env_var)
        if env_path and Path(env_path).exists():
            return env_path
        return shutil.which(name) or name

    def _codex_add_command(self) -> dict[str, Any]:
        spec = self._launch_spec()
        codex = self._find_binary("CODEX_CLI_PATH", "codex")
        args = ["mcp", "add", TRACE_MCP_SERVER_NAME]
        if spec["env"].get("PYTHONPATH"):
            args += ["--env", f"PYTHONPATH={spec['env']['PYTHONPATH']}"]
        args += ["--", spec["command"], *spec["args"]]
        return {
            "binary": codex,
            "args": args,
            "command": _command_line([codex, *args]),
            "prefix": CODEX_MCP_ADD_PREFIX,
        }

    def _claude_add_command(self) -> dict[str, Any]:
        spec = self._launch_spec()
        claude = self._find_binary("CLAUDE_CLI_PATH", "claude")
        args = ["mcp", "add", "--scope", "user", TRACE_MCP_SERVER_NAME]
        if spec["env"].get("PYTHONPATH"):
            args += ["-e", f"PYTHONPATH={spec['env']['PYTHONPATH']}"]
        args += ["--", spec["command"], *spec["args"]]
        return {
            "binary": claude,
            "args": args,
            "command": _command_line([claude, *args]),
            "prefix": CLAUDE_MCP_ADD_PREFIX,
        }

    def _opencode_add_command(self) -> dict[str, Any]:
        opencode = self._find_binary("OPENCODE_CLI_PATH", "opencode")
        args = ["mcp", "add"]
        return {
            "binary": opencode,
            "args": args,
            "command": _command_line([opencode, *args])
            + "\n"
            + self._opencode_trace_config_text(),
            "prefix": OPENCODE_MCP_ADD_PREFIX,
        }

    def _opencode_trace_config_text(self) -> str:
        return json.dumps(
            {"mcp": {TRACE_MCP_SERVER_NAME: self._trace_mcp_config_object()}}, indent=2
        )

    # --- subprocess for claude --------------------------------------------

    def _run_install_command(self, command: str, args: list[str]) -> dict[str, Any]:
        try:
            completed = subprocess.run(
                [command, *args],
                cwd=str(self.project_root),
                env=os.environ.copy(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=20,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "mcp install timed out"}
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        stdout = completed.stdout.decode("utf-8", "replace").strip()
        stderr = completed.stderr.decode("utf-8", "replace").strip()
        if completed.returncode != 0:
            return {
                "ok": False,
                "error": stderr
                or stdout
                or f"mcp install exited {completed.returncode}",
                "stdout": stdout,
                "stderr": stderr,
            }
        return {"ok": True, "stdout": stdout, "stderr": stderr}

    # --- public API --------------------------------------------------------

    def list_rows(self) -> list[dict[str, Any]]:
        spec = self._launch_spec()
        stdio_command = _command_line([spec["command"], *spec["args"]])
        env_line = (
            f"PYTHONPATH={spec['env']['PYTHONPATH']}\n"
            if spec["env"].get("PYTHONPATH")
            else ""
        )

        codex_state = self._inspect_codex_mcp()
        codex_hook_state = self._inspect_codex_hook()
        claude_state = self._inspect_claude_mcp()
        opencode_state = self._inspect_opencode_mcp()
        codex_command = self._codex_add_command()
        claude_command = self._claude_add_command()
        opencode_command = self._opencode_add_command()

        codex_installed = codex_state["installed"] and codex_hook_state["installed"]
        codex_partial = not codex_installed and (
            codex_state["has_trace_section"]
            or codex_hook_state["has_trace_hook"]
            or codex_state["installed"]
            or codex_hook_state["installed"]
        )
        codex_status = (
            "installed"
            if codex_installed
            else ("partial" if codex_partial else "not-installed")
        )
        codex_label = (
            "已添加"
            if codex_installed
            else ("待修复" if codex_partial else "可一键添加")
        )

        claude_status = "installed" if claude_state["installed"] else "not-installed"
        claude_label = "已添加" if claude_state["installed"] else "可一键添加"

        opencode_status = (
            "installed" if opencode_state["installed"] else "not-installed"
        )
        opencode_label = "已添加" if opencode_state["installed"] else "可一键添加"

        return [
            {
                "id": "codex",
                "name": "Codex",
                "tool": TRACE_MCP_TOOL,
                "installed": codex_installed,
                "status": codex_status,
                "status_label": codex_label,
                "can_auto_install": True,
                "action_label": "已添加" if codex_installed else "一键添加",
                "command": codex_command["command"],
                "command_prefix": codex_command["prefix"],
                "config_path": codex_state["config_path"],
                "hook_path": codex_hook_state["hooks_path"],
                "hook_command": self._hook_command("pre"),
                "description": (
                    "Codex 已配置 Trace MCP 与 Trace hooks，新开会话后会主动上报改动文件。"
                    if codex_installed
                    else (
                        "Codex 已有部分或旧 Trace 配置；点击后会替换旧 trace 配置并补齐 hooks。"
                        if codex_partial
                        else "点击后写入 Codex MCP 与 hooks 配置；重启 Codex 后在 /hooks 信任一次即可生效。"
                    )
                ),
            },
            {
                "id": "claude",
                "name": "Claude Code",
                "tool": TRACE_MCP_TOOL,
                "installed": claude_state["installed"],
                "status": claude_status,
                "status_label": claude_label,
                "can_auto_install": True,
                "action_label": "已添加" if claude_state["installed"] else "一键添加",
                "command": claude_command["command"],
                "command_prefix": claude_command["prefix"],
                "config_path": claude_state["config_path"],
                "hook_path": "",
                "hook_command": "",
                "description": (
                    "Claude Code 已配置 Trace MCP；如显示 Pending approval，请在 Claude 中批准一次。"
                    if claude_state["installed"]
                    else "点击后调用 claude mcp add 写入用户级 Trace MCP；重启 Claude 后批准一次即可生效。"
                ),
            },
            {
                "id": "opencode",
                "name": "OpenCode",
                "tool": TRACE_MCP_TOOL,
                "installed": opencode_state["installed"],
                "status": opencode_status,
                "status_label": opencode_label,
                "can_auto_install": True,
                "action_label": "已添加" if opencode_state["installed"] else "一键添加",
                "command": opencode_command["command"],
                "command_prefix": opencode_command["prefix"],
                "config_path": opencode_state["config_path"],
                "hook_path": "",
                "hook_command": "",
                "description": (
                    "OpenCode 已配置 Trace MCP；重启 OpenCode 后生效。"
                    if opencode_state["installed"]
                    else "点击后写入 ~/.config/opencode/opencode.jsonc，重启 OpenCode 后生效。"
                ),
            },
            {
                "id": "other",
                "name": "Other Agents",
                "tool": TRACE_MCP_TOOL,
                "installed": False,
                "status": "manual",
                "status_label": "复制配置",
                "can_auto_install": False,
                "action_label": "复制配置",
                "command": f"{env_line}{stdio_command}",
                "command_prefix": "",
                "config_path": "",
                "hook_path": "",
                "hook_command": "",
                "description": "其他的 agent 请复制到配置文件；支持 MCP stdio 的 agent 可使用这条 Trace server 命令。",
            },
        ]

    def install(self, server_id: str) -> dict[str, Any]:
        if server_id not in {"codex", "claude", "opencode"}:
            return {
                "ok": False,
                "error": "这个 agent 暂不支持自动添加；请复制配置到对应配置文件。",
                "server_id": server_id,
            }

        if server_id == "claude":
            state = self._inspect_claude_mcp()
            command = self._claude_add_command()
            if state["installed"]:
                return {
                    "ok": True,
                    "already_installed": True,
                    "server_id": "claude",
                    "command": command["command"],
                    "config_path": state["config_path"],
                    "restart_required": True,
                }
            result = self._run_install_command(command["binary"], command["args"])
            return {
                **result,
                "server_id": "claude",
                "command": command["command"],
                "config_path": state["config_path"],
                "restart_required": result.get("ok", False),
                "approval_required": result.get("ok", False),
            }

        if server_id == "opencode":
            state = self._inspect_opencode_mcp()
            command = self._opencode_add_command()
            if state["installed"]:
                return {
                    "ok": True,
                    "already_installed": True,
                    "server_id": "opencode",
                    "command": command["command"],
                    "config_path": state["config_path"],
                    "restart_required": True,
                }
            next_state = self._install_opencode_config()
            return {
                "ok": next_state["installed"],
                "server_id": "opencode",
                "command": command["command"],
                "config_path": next_state["config_path"],
                "restart_required": True,
            }

        # codex
        state = self._inspect_codex_mcp()
        hook_state = self._inspect_codex_hook()
        command = self._codex_add_command()
        if state["installed"] and hook_state["installed"]:
            return {
                "ok": True,
                "already_installed": True,
                "server_id": "codex",
                "command": command["command"],
                "config_path": state["config_path"],
                "hook_path": hook_state["hooks_path"],
                "restart_required": False,
            }
        mcp_result = self._install_codex_mcp_config()
        hook_result = self._install_codex_hook_config()
        ok = mcp_result["installed"] and hook_result["installed"]
        return {
            "ok": ok,
            "server_id": "codex",
            "command": command["command"],
            "config_path": mcp_result["config_path"],
            "hook_path": hook_result["hooks_path"],
            "hook_installed": hook_result["installed"],
            "replaced_existing_mcp": state["has_trace_section"]
            and not state["installed"],
            "replaced_existing_hook": hook_state["has_trace_hook"]
            and not hook_state["installed"],
            "restart_required": ok,
        }
