import asyncio
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).parent.parent / "code"
sys.path.insert(0, str(ROOT))


class TestTraceMcpAttribution(unittest.TestCase):
    def test_reported_file_change_beats_workspace_ambiguity(self):
        from daemon.attribution_resolver import resolve_attribution
        from daemon.trace_activity import TraceActivityStore
        from models.agent import AgentInstance

        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td)
            target = workspace / "notes.md"
            target.write_text("hello", encoding="utf-8")
            event_time = time.time()
            store = TraceActivityStore(workspace)
            store.record_files(
                agent="codex",
                files=[str(target)],
                operation="write",
                event_time=event_time,
                source="mcp",
            )

            attr = resolve_attribution(
                workspace,
                target,
                event_time=event_time,
                trace_activity=store,
                scan_workspace=lambda _workspace: [
                    AgentInstance("codex", "Codex CLI", "cli", cwd=str(workspace)),
                    AgentInstance("claude", "Claude Code", "cli", cwd=str(workspace)),
                ],
                scan_global=lambda: [],
            )

            self.assertEqual(attr.agent, "codex")
            self.assertEqual(attr.confidence, 1.0)
            self.assertEqual(attr.detection_method, "trace_mcp")
            self.assertFalse(attr.ambiguous)


class TestTraceMcpServerProtocol(unittest.TestCase):
    def test_stdio_server_handles_byte_length_with_non_ascii_client_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td) / "workspace"
            workspace.mkdir()
            proc = subprocess.Popen(
                [
                    sys.executable,
                    str(Path(__file__).parent.parent / "run_mcp_server.py"),
                    "--workspace",
                    str(workspace),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            def frame(message: dict) -> bytes:
                body = json.dumps(message, ensure_ascii=False).encode("utf-8")
                return b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n" + body

            payload = b"".join(
                [
                    frame(
                        {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "initialize",
                            "params": {
                                "protocolVersion": "2024-11-05",
                                "capabilities": {},
                                "clientInfo": {"name": "探针", "version": "0"},
                            },
                        }
                    ),
                    frame(
                        {
                            "jsonrpc": "2.0",
                            "method": "notifications/initialized",
                            "params": {},
                        }
                    ),
                    frame(
                        {
                            "jsonrpc": "2.0",
                            "id": 2,
                            "method": "tools/list",
                            "params": {},
                        }
                    ),
                ]
            )
            stdout, stderr = proc.communicate(payload, timeout=5)

        self.assertEqual(stderr, b"")
        messages = self._parse_stdio_messages(stdout)
        self.assertEqual([message.get("id") for message in messages], [1, 2])
        tools = messages[1]["result"]["tools"]
        self.assertIn("trace_record_files", [tool["name"] for tool in tools])

    def test_stdio_server_handles_claude_json_line_transport(self):
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td) / "workspace"
            workspace.mkdir()
            proc = subprocess.Popen(
                [
                    sys.executable,
                    str(Path(__file__).parent.parent / "run_mcp_server.py"),
                    "--workspace",
                    str(workspace),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            payload = "\n".join(
                json.dumps(message, ensure_ascii=False)
                for message in [
                    {
                        "jsonrpc": "2.0",
                        "id": 0,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-11-25",
                            "capabilities": {"roots": {}, "elicitation": {}},
                            "clientInfo": {"name": "claude-code", "version": "2.1.195"},
                        },
                    },
                    {
                        "jsonrpc": "2.0",
                        "method": "notifications/initialized",
                        "params": {},
                    },
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/list",
                        "params": {},
                    },
                ]
            )
            stdout, stderr = proc.communicate(payload + "\n", timeout=5)

        self.assertEqual(stderr, "")
        messages = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        self.assertEqual([message.get("id") for message in messages], [0, 1])
        self.assertEqual(messages[0]["result"]["protocolVersion"], "2025-11-25")
        tools = messages[1]["result"]["tools"]
        self.assertIn("trace_record_files", [tool["name"] for tool in tools])

    def test_server_handles_optional_probe_methods(self):
        from mcp.trace_server import TraceMcpServer

        async def run():
            with tempfile.TemporaryDirectory() as td:
                server = TraceMcpServer(workspace=Path(td))
                responses = []
                for request_id, method in enumerate(
                    ["ping", "resources/list", "prompts/list"],
                    start=1,
                ):
                    responses.append(
                        await server.handle_request(
                            {
                                "jsonrpc": "2.0",
                                "id": request_id,
                                "method": method,
                                "params": {},
                            }
                        )
                    )
                return responses

        responses = asyncio.run(run())

        self.assertEqual(responses[0]["result"], {})
        self.assertEqual(responses[1]["result"], {"resources": []})
        self.assertEqual(responses[2]["result"], {"prompts": []})

    def test_server_lists_record_files_tool(self):
        from mcp.trace_server import TraceMcpServer

        async def run():
            with tempfile.TemporaryDirectory() as td:
                server = TraceMcpServer(workspace=Path(td))
                response = await server.handle_request(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/list",
                        "params": {},
                    }
                )
                return response

        response = asyncio.run(run())

        self.assertEqual(response["jsonrpc"], "2.0")
        self.assertEqual(response["id"], 1)
        tools = response["result"]["tools"]
        names = [tool["name"] for tool in tools]
        self.assertIn("trace_record_files", names)
        record_tool = next(tool for tool in tools if tool["name"] == "trace_record_files")
        self.assertIn("inputSchema", record_tool)
        self.assertIn("agent", record_tool["inputSchema"]["properties"])
        self.assertIn("files", record_tool["inputSchema"]["properties"])

    def test_record_files_tool_writes_activity_event(self):
        from mcp.trace_server import TraceMcpServer

        async def run():
            with tempfile.TemporaryDirectory() as td:
                workspace = Path(td)
                target = workspace / "a.txt"
                target.write_text("x", encoding="utf-8")
                server = TraceMcpServer(workspace=workspace)
                response = await server.handle_request(
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {
                            "name": "trace_record_files",
                            "arguments": {
                                "agent": "codex",
                                "files": ["a.txt"],
                                "operation": "write",
                            },
                        },
                    }
                )
                activity = json.loads((workspace / ".trace" / "trace_activity.jsonl").read_text(encoding="utf-8").splitlines()[-1])
                return response, activity

        response, activity = asyncio.run(run())

        self.assertEqual(response["jsonrpc"], "2.0")
        self.assertEqual(response["id"], 2)
        self.assertEqual(activity["agent"], "codex")
        self.assertEqual(activity["source"], "mcp")
        self.assertEqual(activity["files"], ["a.txt"])

    @staticmethod
    def _parse_stdio_messages(data: bytes) -> list[dict]:
        messages: list[dict] = []
        offset = 0
        while offset < len(data):
            header_end = data.find(b"\r\n\r\n", offset)
            if header_end == -1:
                break
            headers = data[offset:header_end].decode("ascii")
            content_length = None
            for line in headers.splitlines():
                name, _, value = line.partition(":")
                if name.lower() == "content-length":
                    content_length = int(value.strip())
                    break
            if content_length is None:
                break
            body_start = header_end + 4
            body_end = body_start + content_length
            messages.append(json.loads(data[body_start:body_end].decode("utf-8")))
            offset = body_end
        return messages


if __name__ == "__main__":
    unittest.main()
