import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent / "code"
sys.path.insert(0, str(ROOT))

from core.electron_init_bridge import init_payload  # noqa: E402


class TestElectronInitBridge(unittest.TestCase):
    def test_init_creates_trace_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            result = init_payload({"workspace": str(ws)})
            self.assertTrue(result["ok"])
            self.assertTrue((ws / ".trace" / "trace.db").exists())

    def test_missing_workspace_returns_error(self):
        result = init_payload({"workspace": "/path/that/does/not/exist"})
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
