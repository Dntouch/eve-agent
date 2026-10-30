import threading
import unittest

from eve_agent.work_activity import WorkActivity


class WorkActivityTest(unittest.TestCase):
    def test_nested_work_releases_activity_after_cancellation(self):
        activity = WorkActivity()

        @activity.track()
        def cancelled():
            self.assertTrue(activity.is_working())
            with activity.track():
                raise KeyboardInterrupt()

        self.assertFalse(activity.is_working())
        with activity.track():
            with self.assertRaises(KeyboardInterrupt):
                cancelled()
            self.assertTrue(activity.is_working())
        self.assertFalse(activity.is_working())

    def test_one_finished_worker_does_not_clear_another_worker(self):
        activity = WorkActivity()
        started, release = threading.Event(), threading.Event()

        def worker():
            with activity.track():
                started.set()
                release.wait(3)

        thread = threading.Thread(target=worker)
        thread.start()
        try:
            self.assertTrue(started.wait(2))
            with activity.track():
                self.assertTrue(activity.is_working())
            self.assertTrue(activity.is_working())
        finally:
            release.set()
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertFalse(activity.is_working())
