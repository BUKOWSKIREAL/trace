"""
Transcript attribution tests
============================
Agent process presence is not enough to prove authorship. These tests lock the
stronger evidence path: local Claude/Codex tool transcripts that mention the
changed file near the filesystem event time.
"""

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).parent.parent / "code"
sys.path.insert(0, str(ROOT))

from daemon.detectors.transcript_detector import (  # noqa: E402
    _claude_project_dir_name,
    find_transcript_attribution,
)


def epoch(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


class TestTranscriptAttribution(unittest.TestCase):
    def test_claude_bash_tool_matching_file_beats_process_guessing(self):
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            workspace = Path("/tmp/test_ws")
            transcript = (
                home / ".claude" / "projects" / "-tmp-test-ws" / "session.jsonl"
            )
            write_jsonl(
                transcript,
                [
                    {
                        "type": "assistant",
                        "timestamp": "2026-05-30T12:56:09.575Z",
                        "cwd": str(workspace),
                        "message": {
                            "content": [
                                {
                                    "type": "tool_use",
                                    "name": "Bash",
                                    "input": {
                                        "command": (
                                            "cd /tmp/test_ws && python3 -c "
                                            '"import openpyxl; '
                                            "wb=openpyxl.load_workbook('foo.xlsx'); "
                                            "wb.save('foo.xlsx')\""
                                        )
                                    },
                                }
                            ]
                        },
                    }
                ],
            )

            attr = find_transcript_attribution(
                workspace,
                workspace / "foo.xlsx",
                epoch("2026-05-30T12:56:17Z"),
                home=home,
            )

        self.assertIsNotNone(attr)
        self.assertEqual(attr.agent, "claude")
        self.assertEqual(attr.detection_method, "claude_transcript")
        self.assertGreaterEqual(attr.confidence, 0.9)
        self.assertFalse(attr.ambiguous)

    def test_codex_exec_command_matching_file_is_high_confidence(self):
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            workspace = Path("/tmp/test_ws")
            transcript = (
                home
                / ".codex"
                / "sessions"
                / "2026"
                / "05"
                / "30"
                / "rollout-test.jsonl"
            )
            write_jsonl(
                transcript,
                [
                    {
                        "type": "session_meta",
                        "payload": {
                            "cwd": str(workspace),
                        },
                    },
                    {
                        "type": "response_item",
                        "timestamp": "2026-05-30T12:42:19.114Z",
                        "payload": {
                            "type": "function_call",
                            "name": "exec_command",
                            "arguments": json.dumps(
                                {
                                    "cmd": "python3 - <<'PY'\nopen('foo.xlsx', 'wb').write(b'x')\nPY",
                                    "workdir": str(workspace),
                                }
                            ),
                        },
                    },
                ],
            )

            attr = find_transcript_attribution(
                workspace,
                workspace / "foo.xlsx",
                epoch("2026-05-30T12:42:24Z"),
                home=home,
            )

        self.assertIsNotNone(attr)
        self.assertEqual(attr.agent, "codex")
        self.assertEqual(attr.detection_method, "codex_transcript")
        self.assertGreaterEqual(attr.confidence, 0.9)

    def test_multiple_transcript_agents_remain_ambiguous(self):
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            workspace = Path("/tmp/test_ws")
            write_jsonl(
                home / ".claude" / "projects" / "-tmp-test-ws" / "session.jsonl",
                [
                    {
                        "type": "assistant",
                        "timestamp": "2026-05-30T12:00:05Z",
                        "cwd": str(workspace),
                        "message": {
                            "content": [
                                {
                                    "type": "tool_use",
                                    "name": "Bash",
                                    "input": {
                                        "command": "python3 -c \"open('foo.txt','w').write('c')\""
                                    },
                                }
                            ]
                        },
                    }
                ],
            )
            write_jsonl(
                home
                / ".codex"
                / "sessions"
                / "2026"
                / "05"
                / "30"
                / "rollout-test.jsonl",
                [
                    {"type": "session_meta", "payload": {"cwd": str(workspace)}},
                    {
                        "type": "response_item",
                        "timestamp": "2026-05-30T12:00:06Z",
                        "payload": {
                            "type": "function_call",
                            "name": "exec_command",
                            "arguments": json.dumps(
                                {
                                    "cmd": "printf codex > foo.txt",
                                    "workdir": str(workspace),
                                }
                            ),
                        },
                    },
                ],
            )

            attr = find_transcript_attribution(
                workspace,
                workspace / "foo.txt",
                epoch("2026-05-30T12:00:07Z"),
                home=home,
            )

        self.assertIsNotNone(attr)
        self.assertEqual(attr.agent, "unknown")
        self.assertEqual(attr.detection_method, "transcript_ambiguous")
        self.assertTrue(attr.ambiguous)
        self.assertEqual(attr.candidates, ["claude", "codex"])

    def test_unmentioned_file_returns_none_for_process_fallback(self):
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            workspace = Path("/tmp/test_ws")
            write_jsonl(
                home / ".claude" / "projects" / "-tmp-test-ws" / "session.jsonl",
                [
                    {
                        "type": "assistant",
                        "timestamp": "2026-05-30T12:00:05Z",
                        "cwd": str(workspace),
                        "message": {
                            "content": [
                                {
                                    "type": "tool_use",
                                    "name": "Bash",
                                    "input": {"command": "touch other.txt"},
                                }
                            ]
                        },
                    }
                ],
            )

            attr = find_transcript_attribution(
                workspace,
                workspace / "foo.txt",
                epoch("2026-05-30T12:00:07Z"),
                home=home,
            )

        self.assertIsNone(attr)

    def test_claude_project_dir_sanitizes_underscore_and_dot(self):
        self.assertEqual(
            _claude_project_dir_name(Path("/Users/test/final_project.v1")),
            "-Users-test-final-project-v1",
        )

    def test_claude_direct_lookup_uses_actual_sanitized_project_dir(self):
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            workspace = Path("/tmp/final_project")
            write_jsonl(
                home / ".claude" / "projects" / "-tmp-final-project" / "session.jsonl",
                [
                    {
                        "type": "assistant",
                        "timestamp": "2026-05-30T13:00:05Z",
                        "cwd": str(workspace),
                        "message": {
                            "content": [
                                {
                                    "type": "tool_use",
                                    "name": "Bash",
                                    "input": {
                                        "command": "python -c \"open('README.md','w').write('x')\""
                                    },
                                }
                            ]
                        },
                    }
                ],
            )

            attr = find_transcript_attribution(
                workspace,
                workspace / "README.md",
                epoch("2026-05-30T13:00:06Z"),
                home=home,
            )

        self.assertIsNotNone(attr)
        self.assertEqual(attr.agent, "claude")

    def test_relative_filename_in_other_project_transcript_does_not_match(self):
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            workspace = Path("/tmp/final_project")
            other = Path("/tmp/other_project")
            write_jsonl(
                home / ".claude" / "projects" / "-tmp-other-project" / "session.jsonl",
                [
                    {
                        "type": "assistant",
                        "timestamp": "2026-05-30T14:00:05Z",
                        "cwd": str(other),
                        "message": {
                            "content": [
                                {
                                    "type": "tool_use",
                                    "name": "Bash",
                                    "input": {"command": "touch README.md"},
                                }
                            ]
                        },
                    }
                ],
            )

            attr = find_transcript_attribution(
                workspace,
                workspace / "README.md",
                epoch("2026-05-30T14:00:06Z"),
                home=home,
            )

        self.assertIsNone(attr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
