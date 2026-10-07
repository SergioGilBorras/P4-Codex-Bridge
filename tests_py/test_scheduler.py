from __future__ import annotations

import tempfile
import threading
import unittest
import os
from pathlib import Path

from p4_codex_bridge.scheduler import ResourceScheduler, RuntimeLimits, canonical_workspace


class SchedulerTests(unittest.TestCase):
    def test_public_exports_hide_scheduler_implementation(self):
        import p4_codex_bridge
        self.assertEqual(p4_codex_bridge.__version__, "1.0.0")
        self.assertFalse(hasattr(p4_codex_bridge, "ResourceScheduler"))
        self.assertFalse(hasattr(p4_codex_bridge, "canonical_workspace"))
        self.assertTrue(hasattr(p4_codex_bridge, "CodexBridge"))
        self.assertTrue(hasattr(p4_codex_bridge, "QueueFullError"))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.limits = RuntimeLimits(global_max_active=2, app_server_max_active=2, exec_max_active=1,
                                    max_active_threads=4, max_queue_size=100,
                                    profile_limits={"analysis": 2, "implementation": 1})
        self.scheduler = ResourceScheduler(self.root / "queue.sqlite", self.limits, instance_id="owner")

    def tearDown(self): self.temp.cleanup()

    def submit(self, n, *, workspace=None, mode="READ", backend="app-server", profile="analysis", priority=0):
        return self.scheduler.submit(turn_id=f"t{n}", thread_id=f"th{n}", backend=backend, profile=profile,
            workspace=workspace or self.root, prompt=f"fake {n}", access_mode=mode, priority=priority,
            submitted_at=f"2026-01-01T00:00:{n:02d}+00:00", bridge_run_id=f"br{n:02d}")

    def test_fifo_wait_reason_workspace_and_auto_eligibility(self):
        first = self.submit(1, mode="WRITE")
        second = self.submit(2, mode="READ")
        claimed = self.scheduler.dispatch()
        self.assertEqual([x["bridge_run_id"] for x in claimed], [first["bridge_run_id"]])
        blocked = self.scheduler.get(second["bridge_run_id"])
        self.assertEqual((blocked["status"], blocked["waiting_reason"], blocked["blocked_by_run_id"]), ("WAITING_FOR_SLOT", "WORKSPACE_LOCK", "br01"))
        self.scheduler.finish("br01", "COMPLETED", finished_at="done")
        self.assertEqual([x["bridge_run_id"] for x in self.scheduler.dispatch()], ["br02"])

    def test_read_shares_write_excludes_and_distinct_workspaces_parallel(self):
        other = self.root / "other"; other.mkdir()
        self.submit(1, mode="READ"); self.submit(2, mode="READ")
        self.assertEqual(len(self.scheduler.dispatch()), 2)
        self.submit(3, workspace=other, mode="WRITE")
        self.assertEqual(self.scheduler.dispatch(), [])
        status = self.scheduler.resources()
        self.assertEqual(len(status["workspace_locks"]), 2)

    def test_queue_limit_cancel_and_persisted_payload(self):
        self.submit(1)
        row = self.scheduler.get("br01")
        self.assertEqual(row["queue_position"], 1)
        self.assertTrue(self.scheduler.cancel("br01", finished_at="cancelled"))
        self.assertEqual(self.scheduler.get("br01")["status"], "CANCELLED")
        self.assertEqual(self.scheduler.dispatch(), [])

    def test_queue_full_is_rejected(self):
        limited = ResourceScheduler(self.root / "limited.sqlite", RuntimeLimits(global_max_active=1,
            app_server_max_active=1, exec_max_active=1, max_active_threads=1, max_queue_size=1,
            profile_limits={"analysis": 1}))
        limited.submit(turn_id="t1", thread_id="th1", backend="app-server", profile="analysis",
            workspace=self.root, prompt="fake", submitted_at="2026-01-01T00:00:00+00:00", bridge_run_id="q1")
        with self.assertRaisesRegex(RuntimeError, "QUEUE_LIMIT"):
            limited.submit(turn_id="t2", thread_id="th2", backend="app-server", profile="analysis",
                workspace=self.root, prompt="fake", submitted_at="2026-01-01T00:00:01+00:00", bridge_run_id="q2")

    def test_limits_persist_and_are_reloaded(self):
        self.scheduler.persist_limits(self.limits)
        restored = ResourceScheduler(self.root / "queue.sqlite", RuntimeLimits(global_max_active=1))
        self.assertEqual(restored.get_persisted_limits()["global_max_active"], 2)
        self.assertEqual(restored.limits.global_max_active, 2)

    def test_priority_then_fifo_and_reason_limits(self):
        self.submit(1, profile="implementation", priority=0)
        self.submit(2, profile="implementation", priority=5)
        self.submit(3, backend="exec")
        claimed = self.scheduler.dispatch()
        self.assertEqual([x["bridge_run_id"] for x in claimed], ["br02", "br03"])
        waiting = self.scheduler.get("br01")
        self.assertEqual(waiting["waiting_reason"], "PROFILE_LIMIT")

    def test_cross_backend_global_and_backend_capacity_accounting(self):
        limits = RuntimeLimits(global_max_active=3, app_server_max_active=2, exec_max_active=2,
                               max_active_threads=8, profile_limits={"analysis": 8})
        scheduler = ResourceScheduler(self.root / "cross.sqlite", limits)
        for n, backend in enumerate(("app-server", "app-server", "exec", "exec"), 1):
            workspace = self.root / f"cross-{n}"
            workspace.mkdir()
            scheduler.submit(turn_id=f"cross-t{n}", thread_id=f"cross-th{n}", backend=backend,
                profile="analysis", workspace=workspace, prompt="fake",
                submitted_at=f"2026-01-01T00:00:0{n}+00:00", bridge_run_id=f"cross{n}")
        self.assertEqual([row["bridge_run_id"] for row in scheduler.dispatch()], ["cross1", "cross2", "cross3"])
        waiting = scheduler.get("cross4")
        self.assertEqual((waiting["status"], waiting["waiting_reason"]), ("WAITING_FOR_SLOT", "GLOBAL_LIMIT"))
        scheduler.finish("cross1", "COMPLETED", finished_at="done")
        self.assertEqual([row["bridge_run_id"] for row in scheduler.dispatch()], ["cross4"])

    def test_cross_backend_share_workspace_lock_and_independent_capacity(self):
        limits = RuntimeLimits(global_max_active=3, app_server_max_active=2, exec_max_active=2,
                               max_active_threads=8, profile_limits={"analysis": 8})
        scheduler = ResourceScheduler(self.root / "cross-lock.sqlite", limits)
        app = scheduler.submit(turn_id="a", thread_id="a", backend="app-server", profile="analysis",
            workspace=self.root, prompt="fake", access_mode="WRITE", submitted_at="1", bridge_run_id="app")
        exec_run = scheduler.submit(turn_id="e", thread_id="e", backend="exec", profile="analysis",
            workspace=self.root, prompt="fake", access_mode="READ", submitted_at="2", bridge_run_id="exec")
        self.assertEqual([row["bridge_run_id"] for row in scheduler.dispatch()], [app["bridge_run_id"]])
        blocked = scheduler.get(exec_run["bridge_run_id"])
        self.assertEqual((blocked["waiting_reason"], blocked["blocked_by_run_id"]), ("WORKSPACE_LOCK", "app"))
        scheduler.finish("app", "COMPLETED", finished_at="done")
        self.assertEqual([row["bridge_run_id"] for row in scheduler.dispatch()], ["exec"])

    def test_prompt_limit_rejected_before_persistence(self):
        with self.assertRaisesRegex(ValueError, "1 MiB"):
            self.scheduler.submit(turn_id="large", thread_id="large", backend="exec", profile="analysis",
                workspace=self.root, prompt="x" * (1024 * 1024 + 1), submitted_at="now")
        self.assertEqual(self.scheduler.list_runs(), [])

    def test_atomic_competing_dispatchers_claim_once(self):
        for n in range(10): self.submit(n)
        output = []
        threads = [threading.Thread(target=lambda: output.extend(self.scheduler.dispatch())) for _ in range(4)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        ids = [row["bridge_run_id"] for row in output]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), 2)

    def test_restart_preserves_queue_but_marks_inflight_lost(self):
        self.submit(1, mode="WRITE"); self.submit(2, mode="READ")
        self.scheduler.dispatch()
        lost = self.scheduler.reconcile_after_restart(finished_at="restart")
        self.assertEqual(lost, ["br01"])
        self.assertEqual(self.scheduler.get("br01")["status"], "LOST")
        self.assertEqual(self.scheduler.get("br02")["status"], "WAITING_FOR_SLOT")
        self.assertEqual([x["bridge_run_id"] for x in self.scheduler.dispatch()], ["br02"])

    def test_fake_stress_50_jobs_respects_capacity_and_workspace_exclusion(self):
        limits = RuntimeLimits(global_max_active=4, app_server_max_active=4, exec_max_active=4, max_active_threads=16, max_queue_size=60,
                               profile_limits={"analysis": 4})
        scheduler = ResourceScheduler(self.root / "stress.sqlite", limits)
        workspaces = [self.root / "w1", self.root / "w2"]
        for workspace in workspaces: workspace.mkdir()
        for n in range(50):
            scheduler.submit(turn_id=f"t{n}", thread_id=f"th{n}", backend="app-server", profile="analysis",
                workspace=workspaces[n % 2], prompt="fake", access_mode="WRITE", submitted_at=f"2026-01-01T00:{n//60:02}:{n%60:02}+00:00", bridge_run_id=f"stress{n:02}")
        done = set(); peak = 0
        while len(done) < 50:
            claimed = scheduler.dispatch()
            resources = scheduler.resources()
            self.assertLessEqual(len(resources["active_runs"]), 4)
            self.assertFalse(done.intersection(x["bridge_run_id"] for x in claimed))
            peak = max(peak, len(resources["active_runs"]))
            for item in claimed:
                done.add(item["bridge_run_id"])
                scheduler.finish(item["bridge_run_id"], "COMPLETED", finished_at="fake")
        self.assertEqual(len(done), 50)
        self.assertLessEqual(peak, 2)

    def test_canonical_path(self):
        self.assertEqual(canonical_workspace(self.root), canonical_workspace(self.root / "."))
        if os.name == "nt":
            self.assertEqual(canonical_workspace(self.root), canonical_workspace(str(self.root).upper().replace("\\", "/")))


if __name__ == "__main__": unittest.main()
