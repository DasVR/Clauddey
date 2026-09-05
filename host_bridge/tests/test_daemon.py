import os
import sys
import unittest
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import daemon


@unittest.skipUnless(sys.platform == "win32", "named-mutex singleton is Windows-only for now")
class SingletonTests(unittest.TestCase):
    def _unique_name(self) -> str:
        return f"ClauddeyTestMutex-{uuid.uuid4().hex}"

    def test_acquire_then_release_allows_reacquiring(self):
        name = self._unique_name()
        self.assertTrue(daemon.acquire_singleton(name))
        daemon.release_singleton()
        # Mutex was released; a fresh acquire under the same name should
        # succeed again rather than reporting "already running".
        self.assertTrue(daemon.acquire_singleton(name))
        daemon.release_singleton()

    def test_second_acquire_is_refused_while_first_is_held(self):
        name = self._unique_name()
        self.assertTrue(daemon.acquire_singleton(name))
        try:
            self.assertFalse(daemon.acquire_singleton(name))
        finally:
            daemon.release_singleton()

    def test_release_frees_the_slot_for_a_forcibly_killed_owner(self):
        """A crash/force-kill releases the OS mutex immediately (no pidfile to
        go stale), unlike PID-based liveness checks which can be fooled by
        PID reuse. We can't literally crash this process, so simulate the
        "owner is gone" case by releasing without a graceful shutdown path
        and confirming the slot is immediately reusable."""
        name = self._unique_name()
        daemon.acquire_singleton(name)
        daemon.release_singleton()
        self.assertTrue(daemon.acquire_singleton(name))
        daemon.release_singleton()
