"""
DaemonManager 单元测试
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).parent.parent / "code"
sys.path.insert(0, str(ROOT))

from daemon.manager import DaemonManager  # noqa: E402


def _manager_patches():
    return (
        patch("daemon.manager.Repository"),
        patch("daemon.manager.RuntimeConfig"),
        patch("daemon.manager.CommitBatcher"),
        patch("daemon.manager.start_watcher"),
        patch("daemon.manager.AgentActivityRecorder"),
    )


class TestDaemonManagerStart(unittest.TestCase):
    def test_start_creates_all_components(self):
        with patch("daemon.manager.Repository") as MockRepo, \
                patch("daemon.manager.RuntimeConfig") as MockConfig, \
                patch("daemon.manager.CommitBatcher") as MockBatcher, \
                patch("daemon.manager.start_watcher") as mock_start_watcher, \
                patch("daemon.activity_recorder.AgentActivityRecorder") as MockRecorder:
            mock_observer = MagicMock()
            mock_handler = MagicMock()
            mock_start_watcher.return_value = (mock_observer, mock_handler)
            MockRepo.return_value.reconcile_offline_changes.return_value = None
            MockConfig.return_value.ignore_patterns = []
            MockConfig.return_value.tracking_enabled = True
            MockConfig.return_value.forced_agent_override.return_value = None
            MockConfig.return_value.high_precision_mode = False

            dm = DaemonManager()
            ws = Path("/tmp/test_ws")
            dm.start(ws)

            MockRepo.assert_called_once_with(ws)
            MockRepo.return_value.init_if_needed.assert_called_once()
            MockBatcher.assert_called_once_with(repo=MockRepo.return_value)
            mock_start_watcher.assert_called_once_with(
                workspace=ws,
                batcher=MockBatcher.return_value,
                ignore_patterns=[],
            )
            MockRecorder.return_value.start.assert_called_once()

    def test_start_sets_all_attributes(self):
        with patch("daemon.manager.Repository") as MockRepo, \
                patch("daemon.manager.RuntimeConfig") as MockConfig, \
                patch("daemon.manager.CommitBatcher"), \
                patch("daemon.manager.start_watcher") as mock_start_watcher, \
                patch("daemon.activity_recorder.AgentActivityRecorder"):
            mock_start_watcher.return_value = (MagicMock(), MagicMock())
            MockRepo.return_value.reconcile_offline_changes.return_value = None
            MockConfig.return_value.ignore_patterns = []
            MockConfig.return_value.tracking_enabled = True
            MockConfig.return_value.forced_agent_override.return_value = None
            MockConfig.return_value.high_precision_mode = False

            dm = DaemonManager()
            ws = Path("/tmp/test_ws")
            dm.start(ws)
            self.assertEqual(dm.workspace, ws)
            self.assertIsNotNone(dm.repo)
            self.assertIsNotNone(dm.batcher)
            self.assertIsNotNone(dm.observer)
            self.assertIsNotNone(dm.handler)
            self.assertIsNotNone(dm.recorder)


class TestDaemonManagerStop(unittest.TestCase):
    def test_stop_calls_in_correct_order(self):
        with patch("daemon.manager.Repository") as MockRepo, \
                patch("daemon.manager.RuntimeConfig") as MockConfig, \
                patch("daemon.manager.CommitBatcher") as MockBatcher, \
                patch("daemon.manager.start_watcher") as mock_start_watcher, \
                patch("daemon.activity_recorder.AgentActivityRecorder") as MockRecorder:
            mock_observer = MagicMock()
            mock_handler = MagicMock()
            mock_start_watcher.return_value = (mock_observer, mock_handler)
            MockRepo.return_value.reconcile_offline_changes.return_value = None
            MockConfig.return_value.ignore_patterns = []
            MockConfig.return_value.tracking_enabled = True
            MockConfig.return_value.forced_agent_override.return_value = None
            MockConfig.return_value.high_precision_mode = False

            dm = DaemonManager()
            dm.start(Path("/tmp/test_ws"))

            call_order = []
            mock_observer.stop.side_effect = lambda: call_order.append("observer.stop")
            mock_handler.shutdown.side_effect = lambda: call_order.append("handler.shutdown")
            MockRecorder.return_value.stop.side_effect = lambda: call_order.append("recorder.stop")
            MockBatcher.return_value.force_flush_all.side_effect = \
                lambda: call_order.append("batcher.force_flush_all")

            dm.stop()

            self.assertEqual(call_order, [
                "observer.stop",
                "handler.shutdown",
                "recorder.stop",
                "batcher.force_flush_all",
            ])

    def test_stop_clears_all_attributes(self):
        with patch("daemon.manager.Repository") as MockRepo, \
                patch("daemon.manager.RuntimeConfig") as MockConfig, \
                patch("daemon.manager.CommitBatcher"), \
                patch("daemon.manager.start_watcher") as mock_start_watcher, \
                patch("daemon.activity_recorder.AgentActivityRecorder"):
            mock_start_watcher.return_value = (MagicMock(), MagicMock())
            MockRepo.return_value.reconcile_offline_changes.return_value = None
            MockConfig.return_value.ignore_patterns = []
            MockConfig.return_value.tracking_enabled = True
            MockConfig.return_value.forced_agent_override.return_value = None
            MockConfig.return_value.high_precision_mode = False

            dm = DaemonManager()
            dm.start(Path("/tmp/test_ws"))
            dm.stop()
            self.assertIsNone(dm.workspace)
            self.assertIsNone(dm.repo)
            self.assertIsNone(dm.batcher)
            self.assertIsNone(dm.observer)
            self.assertIsNone(dm.handler)
            self.assertIsNone(dm.recorder)

    def test_stop_without_start_is_safe(self):
        dm = DaemonManager()
        dm.stop()
        self.assertIsNone(dm.workspace)


class TestDaemonManagerRestart(unittest.TestCase):
    def test_restart_stops_old_and_starts_new(self):
        with patch("daemon.manager.Repository") as MockRepo, \
                patch("daemon.manager.RuntimeConfig") as MockConfig, \
                patch("daemon.manager.CommitBatcher"), \
                patch("daemon.manager.start_watcher") as mock_start_watcher, \
                patch("daemon.activity_recorder.AgentActivityRecorder"):
            obs1, hnd1 = MagicMock(name="obs1"), MagicMock(name="hnd1")
            obs2, hnd2 = MagicMock(name="obs2"), MagicMock(name="hnd2")
            mock_start_watcher.side_effect = [(obs1, hnd1), (obs2, hnd2)]
            MockRepo.return_value.reconcile_offline_changes.return_value = None
            MockConfig.return_value.ignore_patterns = []
            MockConfig.return_value.tracking_enabled = True
            MockConfig.return_value.forced_agent_override.return_value = None
            MockConfig.return_value.high_precision_mode = False

            dm = DaemonManager()
            ws_a = Path("/tmp/ws_a")
            ws_b = Path("/tmp/ws_b")

            dm.start(ws_a)
            self.assertIs(dm.observer, obs1)

            dm.restart(ws_b)
            obs1.stop.assert_called_once()
            self.assertIs(dm.observer, obs2)
            self.assertEqual(dm.workspace, ws_b)

    def test_start_twice_is_idempotent_stop_then_start(self):
        with patch("daemon.manager.Repository") as MockRepo, \
                patch("daemon.manager.RuntimeConfig") as MockConfig, \
                patch("daemon.manager.CommitBatcher"), \
                patch("daemon.manager.start_watcher") as mock_start_watcher, \
                patch("daemon.activity_recorder.AgentActivityRecorder"):
            obs1, hnd1 = MagicMock(), MagicMock()
            obs2, hnd2 = MagicMock(), MagicMock()
            mock_start_watcher.side_effect = [(obs1, hnd1), (obs2, hnd2)]
            MockRepo.return_value.reconcile_offline_changes.return_value = None
            MockConfig.return_value.ignore_patterns = []
            MockConfig.return_value.tracking_enabled = True
            MockConfig.return_value.forced_agent_override.return_value = None
            MockConfig.return_value.high_precision_mode = False

            dm = DaemonManager()
            dm.start(Path("/tmp/a"))
            dm.start(Path("/tmp/b"))
            obs1.stop.assert_called_once()
            self.assertIs(dm.observer, obs2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
