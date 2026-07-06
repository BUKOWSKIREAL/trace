"""
Trace MCP stdio server.

The server exposes tools that let coding agents explicitly report file changes
to Trace. These reports are then used by the attribution resolver before passive
process/transcript heuristics.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

# Add parent directory to path to allow imports when run as module
if __name__ == "__main__":
    _parent = Path(__file__).resolve().parent.parent
    if str(_parent) not in sys.path:
        sys.path.insert(0, str(_parent))

from daemon.trace_activity import TraceActivityStore


RECORD_FILES_TOOL = {
    "name": "trace_record_files",
    "description": (
        "Report files changed by the current agent so Trace can attribute the "
        "next filesystem events accurately."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "agent": {
                "type": "string",
                "description": "Agent key, for example codex, claude, opencode.",
            },
            "files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Workspace-relative or absolute file paths.",
            },
            "operation": {
                "type": "string",
                "description": "Operation label such as write, create, delete, or rename.",
                "default": "write",
            },
            "confidence": {
                "type": "number",
                "description": "Confidence score from 0 to 1.",
                "default": 1.0,
            },
        },
        "required": ["agent", "files"],
        "additionalProperties": False,
    },
}


class TraceMcpServer:
    def __init__(self, workspace: Path):
        self.workspace = workspace.expanduser().resolve(strict=False)
        self.store = TraceActivityStore(self.workspace)

    async def handle_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params") or {}
        client_protocol = str(params.get("protocolVersion") or "2024-11-05")

        try:
            if method == "initialize":
                return self._result(
                    request_id,
                    {
                        "protocolVersion": client_protocol,
                        "capabilities": {
                            "tools": {},
                            "resources": {},
                            "prompts": {},
                        },
                        "serverInfo": {"name": "trace-mcp", "version": "0.1.0"},
                    },
                )
            if method == "notifications/initialized":
                return None
            if method == "ping":
                return self._result(request_id, {})
            if method == "tools/list":
                return self._result(request_id, {"tools": [RECORD_FILES_TOOL]})
            if method == "tools/call":
                return self._result(request_id, self._call_tool(params))
            if method == "resources/list":
                return self._result(request_id, {"resources": []})
            if method == "prompts/list":
                return self._result(request_id, {"prompts": []})
            return self._error(request_id, -32601, f"method not found: {method}")
        except Exception as exc:
            return self._error(request_id, -32603, str(exc))

    def _call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name != "trace_record_files":
            raise ValueError(f"unknown tool: {name}")
        if not isinstance(arguments, dict):
            raise ValueError("arguments must be an object")

        agent = str(arguments.get("agent") or "").strip()
        files = arguments.get("files")
        if not agent:
            raise ValueError("agent is required")
        if not isinstance(files, list) or not all(isinstance(item, str) for item in files):
            raise ValueError("files must be an array of strings")

        operation = str(arguments.get("operation") or "write")
        confidence = float(arguments.get("confidence", 1.0))
        report = self.store.record_files(
            agent=agent,
            files=files,
            operation=operation,
            source="mcp",
            confidence=confidence,
        )
        return {
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"Trace recorded {len(report.files)} file(s) for "
                        f"{report.agent} in {self.workspace}"
                    ),
                }
            ],
            "structuredContent": {
                "ok": True,
                "agent": report.agent,
                "files": report.files,
                "operation": report.operation,
                "source": report.source,
            },
        }

    @staticmethod
    def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }


def _read_header_or_json_line() -> bytes | None:
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        line = line.rstrip(b"\r\n")
        if not line:
            continue
        return line


def _read_message() -> tuple[dict[str, Any], str] | None:
    first = _read_header_or_json_line()
    if first is None:
        return None

    if first.startswith(b"{"):
        try:
            return json.loads(first.decode("utf-8")), "jsonl"
        except json.JSONDecodeError:
            return None

    content_length = 0
    line = first
    while True:
        if line.lower().startswith(b"content-length:"):
            content_length = int(line.split(b":", 1)[1].strip())
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        line = line.rstrip(b"\r\n")
        if not line:
            break
    if not content_length:
        return None
    body = sys.stdin.buffer.read(content_length)
    try:
        return json.loads(body.decode("utf-8")), "header"
    except json.JSONDecodeError:
        return None


def _write_message(data: dict[str, Any], transport: str) -> None:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    if transport == "jsonl":
        sys.stdout.buffer.write(body + b"\n")
    else:
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        sys.stdout.buffer.write(header + body)
    sys.stdout.buffer.flush()


async def serve_stdio(workspace: Path) -> None:
    server = TraceMcpServer(workspace)
    while True:
        message = _read_message()
        if message is None:
            break
        request, transport = message
        response = await server.handle_request(request)
        if response is None:
            continue
        _write_message(response, transport)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Trace MCP stdio server")
    parser.add_argument(
        "--workspace",
        default=".",
        help="Workspace whose .trace/trace_activity.jsonl should receive reports.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    asyncio.run(serve_stdio(Path(args.workspace)))


if __name__ == "__main__":
    main()
