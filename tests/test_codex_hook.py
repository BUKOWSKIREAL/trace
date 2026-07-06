import json
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).parent.parent / "code"
sys.path.insert(0, str(ROOT))


class TestCodexTraceHook(unittest.TestCase):
    def test_pre_apply_patch_report_beats_multi_agent_ambiguity(self):
        from daemon.attribution_resolver import resolve_attribution
        from daemon.trace_activity import TraceActivityStore
        from hooks.trace_codex_hook import run_hook
        from models.agent import AgentInstance

        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td)
            target = workspace / "notes.md"
            target.write_text("old", encoding="utf-8")
            event_time = time.time()

            run_hook(
                {
                    "tool_name": "apply_patch",
                    "tool_input": {
                        "patch": "\n".join(
                            [
                                "*** Begin Patch",
                                "*** Update File: notes.md",
                                "@@",
                                "-old",
                                "+new",
                                "*** End Patch",
                            ]
                        )
                    },
                },
                workspace=workspace,
                phase="pre",
                event_time=event_time,
            )

            store = TraceActivityStore(workspace)
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
            activity = json.loads(
                (workspace / ".trace" / "trace_activity.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()[-1]
            )

            self.assertEqual(activity["agent"], "codex")
            self.assertEqual(activity["files"], ["notes.md"])
            self.assertEqual(activity["source"], "codex_hook_pre")
            self.assertEqual(attr.agent, "codex")
            self.assertEqual(attr.confidence, 1.0)
            self.assertEqual(attr.detection_method, "trace_codex_hook_pre")

    def test_post_bash_hook_records_recently_modified_workspace_file(self):
        from hooks.trace_codex_hook import run_hook

        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td)
            target = workspace / "report.docx"
            target.write_text("generated", encoding="utf-8")
            now = time.time()
            target.touch()

            reports = run_hook(
                {
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": "python scripts/make_report.py",
                    },
                },
                workspace=workspace,
                phase="post",
                event_time=now + 0.1,
            )
            activity = json.loads(
                (workspace / ".trace" / "trace_activity.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()[-1]
            )

            self.assertEqual(len(reports), 1)
            self.assertEqual(activity["agent"], "codex")
            self.assertEqual(activity["files"], ["report.docx"])
            self.assertEqual(activity["source"], "codex_hook_post")
            self.assertEqual(activity["confidence"], 0.98)


if __name__ == "__main__":
    unittest.main()
