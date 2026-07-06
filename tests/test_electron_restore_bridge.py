"""
Electron restore bridge contract tests.

Electron should restore files through the existing Repository API instead of
duplicating filesystem/version logic in JavaScript.
"""
import json
import sys
import time
import unittest
from pathlib import Path

PROJECT = Path(__file__).parent.parent
CODE = PROJECT / "code"
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(CODE))

from core.repository import Repository  # noqa: E402
from models.agent import AgentAttribution  # noqa: E402
from models.change import Change  # noqa: E402
from tests._tempdir import temp_repository  # noqa: E402


def make_change(path: Path, kind: str = "upsert") -> Change:
    return Change(
        file_path=path,
        event_time=time.time(),
        attribution=AgentAttribution(agent="human", confidence=1.0),
        kind=kind,
    )


class TestElectronRestoreBridge(unittest.TestCase):
    def test_payload_restores_file_through_repository(self):
        from core.electron_restore_bridge import restore_payload

        with temp_repository() as (repo, workspace):
            repo.init_if_needed()
            target = workspace / "notes.md"

            target.write_text("old\n", encoding="utf-8")
            old_commit = repo.commit("human", [make_change(target)])
            target.write_text("new\n", encoding="utf-8")
            repo.commit("human", [make_change(target)])

            result = restore_payload(
                {
                    "workspace": str(workspace),
                    "commit_id": old_commit,
                    "file_path": "notes.md",
                    "backup_current": True,
                }
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["commit_id"], old_commit)
            self.assertEqual(result["file_path"], "notes.md")
            self.assertIsNone(result["backup_id"])
            self.assertEqual(target.read_text(encoding="utf-8"), "old\n")
            json.dumps(result, ensure_ascii=False)

    def test_payload_rejects_missing_file(self):
        from core.electron_restore_bridge import restore_payload

        with temp_repository() as (repo, workspace):
            repo.init_if_needed()
            target = workspace / "notes.md"
            target.write_text("old\n", encoding="utf-8")
            commit_id = repo.commit("human", [make_change(target)])

            result = restore_payload(
                {
                    "workspace": str(workspace),
                    "commit_id": commit_id,
                    "file_path": "missing.md",
                }
            )

            self.assertFalse(result["ok"])
            self.assertIn("不存在", result["error"])


if __name__ == "__main__":
    unittest.main()
