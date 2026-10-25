import threading
import unittest

from eve_agent.turn_lifecycle import TurnCompletionStore


class TurnCompletionStoreTest(unittest.TestCase):
    def test_all_presentation_and_audio_outcomes_preserve_completed_turn(self):
        for presentation_status in ("success", "error"):
            for audio_status in ("success", "error"):
                with self.subTest(presentation=presentation_status, audio=audio_status):
                    store = TurnCompletionStore()
                    store.register("turn-1", "conversation-1", presentation=True, audio=True)
                    store.update("turn-1", "presentation", {
                        "turn_id": "turn-1", "status": presentation_status,
                        "revision": 3,
                    })
                    self.assertEqual(store.get("turn-1")["status"], "pending")
                    store.update("turn-1", "audio", {
                        "turn_id": "turn-1", "status": audio_status,
                        "audio_wav_base64": "UklGRg==" if audio_status == "success" else "",
                    })
                    result = store.get("turn-1")
                    self.assertEqual(result["status"], "complete")
                    self.assertEqual(result["turn_id"], "turn-1")
                    self.assertEqual(result["presentation"]["status"], presentation_status)
                    self.assertEqual(result["audio"]["status"], audio_status)

    def test_late_results_stay_with_original_turn(self):
        store = TurnCompletionStore()
        store.register("turn-a", "conversation", presentation=True, audio=False)
        store.register("turn-b", "conversation", presentation=True, audio=False)
        store.update("turn-b", "presentation", {"turn_id": "turn-b", "status": "success"})
        store.update("turn-a", "presentation", {"turn_id": "turn-a", "status": "stale"})
        self.assertEqual(store.get("turn-a")["presentation"]["turn_id"], "turn-a")
        self.assertEqual(store.get("turn-b")["presentation"]["turn_id"], "turn-b")

    def test_concurrent_terminal_updates_claim_completion_exactly_once(self):
        store = TurnCompletionStore()
        store.register("turn-1", "conversation", presentation=True, audio=True)
        barrier = threading.Barrier(3)
        claims = []

        def update(component):
            barrier.wait()
            claims.append(store.update(
                "turn-1", component,
                {"turn_id": "turn-1", "status": "success"},
            ))

        threads = [
            threading.Thread(target=update, args=("presentation",)),
            threading.Thread(target=update, args=("audio",)),
        ]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join()

        self.assertEqual(1, claims.count(True))
        self.assertEqual(1, claims.count(False))
        self.assertEqual("complete", store.get("turn-1")["status"])


if __name__ == "__main__":
    unittest.main()
