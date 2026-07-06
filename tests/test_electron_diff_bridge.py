"""
Electron diff bridge contract tests.

Electron cannot parse document blobs itself; it should call into the existing
Python handler registry so supported binary container formats like .docx get
semantic diffs instead of a generic binary message.
"""

import json
import sys
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).parent.parent
CODE = ROOT / "code"
sys.path.insert(0, str(CODE))

from core.storage import BlobStorage  # noqa: E402
from docx import Document  # noqa: E402


def make_docx(paragraphs: list[str]) -> bytes:
    doc = Document()
    for text in paragraphs:
        doc.add_paragraph(text)
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


class TestElectronDiffBridge(unittest.TestCase):
    def _store(self, workspace: Path, blob: bytes) -> str:
        storage = BlobStorage(workspace / ".trace" / "objects")
        storage.ensure_dir()
        return storage.put(blob)

    def test_docx_diff_uses_registered_handler(self):
        from core.electron_diff_bridge import render_file_diff

        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td)
            old_hash = self._store(workspace, make_docx(["标题", "旧内容", "结尾"]))
            new_hash = self._store(workspace, make_docx(["标题", "新内容", "结尾"]))

            rows = render_file_diff(workspace, "docs/report.docx", old_hash, new_hash)

        tags = [row["tag"] for row in rows]
        text = "\n".join(row["text"] for row in rows)
        self.assertIn("removed", tags)
        self.assertIn("added", tags)
        self.assertIn("旧内容", text)
        self.assertIn("新内容", text)
        self.assertNotIn("二进制文件，未做内容 diff", text)

    def test_payload_renderer_returns_json_safe_rows(self):
        from core.electron_diff_bridge import render_payload

        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td)
            old_hash = self._store(workspace, b"abc")
            new_hash = self._store(workspace, b"abcdef")

            result = render_payload(
                {
                    "workspace": str(workspace),
                    "file_path": "archive.bin",
                    "prev_hash": old_hash,
                    "cur_hash": new_hash,
                }
            )

        encoded = json.dumps(result, ensure_ascii=False)
        self.assertIn('"ok": true', encoded)
        self.assertIn("二进制文件，未做内容 diff", encoded)

    def test_batch_payload_renders_multiple_files_in_one_process(self):
        from core.electron_diff_bridge import render_payload

        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td)
            old_a = self._store(workspace, b"one\n")
            new_a = self._store(workspace, b"two\n")
            old_b = self._store(workspace, b"alpha")
            new_b = self._store(workspace, b"alpha beta")

            result = render_payload(
                {
                    "workspace": str(workspace),
                    "files": [
                        {"file_path": "a.txt", "prev_hash": old_a, "cur_hash": new_a},
                        {"file_path": "b.bin", "prev_hash": old_b, "cur_hash": new_b},
                    ],
                }
            )

        self.assertTrue(result["ok"])
        self.assertIn("a.txt", result["files"])
        self.assertIn("b.bin", result["files"])
        self.assertTrue(result["files"]["a.txt"]["ok"])
        self.assertTrue(result["files"]["b.bin"]["ok"])


if __name__ == "__main__":
    unittest.main()
