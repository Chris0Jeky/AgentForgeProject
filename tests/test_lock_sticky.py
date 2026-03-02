import tempfile
import time
import unittest
from pathlib import Path

from agentforge.core.config import RepoConfig
from agentforge.core.locks import acquire_lock, renew_lock, mark_lock_sticky, list_locks


class TestStickyLocks(unittest.TestCase):
    def test_sticky_mark_and_renew(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = RepoConfig(state_dir=".agentforge/state")

            li = acquire_lock(root=root, cfg=cfg, group="repo", agent="a1", task="t1", ttl_sec=10, sticky=True, branch="a1/t1")
            self.assertTrue(li.sticky)
            self.assertEqual(li.branch, "a1/t1")

            li2 = mark_lock_sticky(root=root, cfg=cfg, group="repo", agent="a1", task="t1", sticky=True, pr_number=123, branch="a1/t1")
            self.assertEqual(li2.pr_number, 123)
            self.assertTrue(li2.sticky)

            before = li2.expires_ts
            time.sleep(1)
            li3 = renew_lock(root=root, cfg=cfg, group="repo", ttl_sec=20, force=True)
            self.assertGreater(li3.expires_ts, before)
            self.assertEqual(li3.ttl_sec, 20)

            locks = list_locks(root=root, cfg=cfg)
            self.assertEqual(len(locks), 1)
            self.assertEqual(locks[0].pr_number, 123)


if __name__ == "__main__":
    unittest.main()
