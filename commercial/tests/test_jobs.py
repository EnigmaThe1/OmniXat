from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from omnixat_core.access import Principal
from omnixat_core.jobs import JobStore


class DurableJobsTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "jobs.sqlite3"
        self.now = 1000.0
        self.clock = lambda: self.now
        self.store = JobStore(self.path, clock=self.clock)
        self.agent = Principal("agent", "a", "editor", actor_kind="agent")
        self.other = Principal("other", "b", "editor", actor_kind="agent")

    def create(self):
        return self.store.create(self.agent, "a", "batch-1", {"evidence_ids": ["fictional-1"]})

    def test_same_batch_is_idempotent_and_different_payload_conflicts(self):
        first = self.create()
        self.assertEqual(self.create(), first)
        with self.assertRaises(ValueError):
            self.store.create(self.agent, "a", "batch-1", {"evidence_ids": ["fictional-2"]})

    def test_tenants_cannot_read_or_claim_each_others_jobs(self):
        job = self.create()
        with self.assertRaises(KeyError):
            self.store.get(self.other, "b", job)
        with self.assertRaises(ValueError):
            self.store.claim(self.other, "b", job)
        with self.assertRaises(PermissionError):
            self.store.get(self.other, "a", job)

    def test_resume_survives_new_store_instance(self):
        job = self.create()
        token = self.store.claim(self.agent, "a", job)
        self.store.checkpoint(self.agent, "a", job, token, {"step": "matched", "entry_ids": ["entry-1"]})
        restored = JobStore(self.path, clock=self.clock)
        self.assertEqual(restored.get(self.agent, "a", job)["checkpoint"]["step"], "matched")

    def test_active_claim_excludes_second_worker(self):
        job = self.create()
        self.store.claim(self.agent, "a", job)
        second = JobStore(self.path, clock=self.clock)
        with self.assertRaises(ValueError):
            second.claim(self.agent, "a", job)

    def test_expired_worker_cannot_overwrite_new_claim(self):
        job = self.create()
        old = self.store.claim(self.agent, "a", job, lease_seconds=1)
        self.now += 2
        new = self.store.claim(self.agent, "a", job)
        with self.assertRaises(ValueError):
            self.store.checkpoint(self.agent, "a", job, old, {"step": "stale"})
        self.store.checkpoint(self.agent, "a", job, new, {"step": "current"}, complete=True)
        self.assertEqual(self.store.get(self.agent, "a", job)["status"], "completed")
        with self.assertRaises(ValueError):
            self.store.claim(self.agent, "a", job)


if __name__ == "__main__":
    unittest.main()
