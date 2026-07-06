import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parent.parent


class TestElectronBridge(unittest.TestCase):
    def test_bridge_passes_remaining_argv_to_mcp_server(self):
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td) / "workspace"
            workspace.mkdir()

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
                                "clientInfo": {"name": "TraceBridge", "version": "0"},
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
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "code" / "electron_bridge.py"),
                    "mcp.trace_server",
                    "--workspace",
                    str(workspace),
                ],
                input=payload,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={**os.environ, "PYTHONPATH": str(ROOT / "code")},
                timeout=5,
                check=True,
            )

        self.assertEqual(completed.stderr, b"")
        messages = self._parse_stdio_messages(completed.stdout)
        self.assertEqual([message.get("id") for message in messages], [1, 2])
        self.assertIn(
            "trace_record_files",
            [tool["name"] for tool in messages[1]["result"]["tools"]],
        )

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
