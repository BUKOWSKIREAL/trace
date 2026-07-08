import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))


class TuiEntry(unittest.TestCase):
    def test_run_with_tui_is_importable_and_builds_app(self):
        import main
        from tui.app import TraceApp

        class _D:
            workspace = Path("/tmp")
            def start(self, ws): pass
            def stop(self): pass

        self.assertTrue(hasattr(main, "_run_with_tui"))
        app = TraceApp(daemon=_D())
        self.assertIsInstance(app, TraceApp)


if __name__ == "__main__":
    unittest.main()
