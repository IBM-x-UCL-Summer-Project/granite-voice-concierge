import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from voice_concierge.orchestration import MemoryManagerGateway, OfflineTTSSpeechGateway
from voice_concierge.reasoning.types import MemoryAction

try:
    from voice_concierge.voice_output.tts_pipeline import OfflineTTS
except ImportError:
    OfflineTTS = None


class FakeMemoryManager:
    def __init__(self) -> None:
        self.retrieve_calls = []
        self.store_calls = []
        self.process_calls = []

    def retrieve_similar(self, query, top_k=5, person=None, topic=None, layer=None):
        self.retrieve_calls.append(
            {
                "query": query,
                "top_k": top_k,
                "person": person,
                "topic": topic,
                "layer": layer,
            }
        )
        return [{"content": "remembered item"}, {"missing": "content"}]

    def store_memory(self, **kwargs):
        self.store_calls.append(kwargs)
        return True, "stored_successfully", 123

    def process_memory_action(self, action):
        self.process_calls.append(action)
        return True, "processed"


class FakeTTS:
    def __init__(self) -> None:
        self.speak_calls = []
        self.stop_calls = 0

    def speak(self, text, length_scale=1.2):
        self.speak_calls.append((text, length_scale))
        return True

    def stop(self):
        self.stop_calls += 1
        return True


class OrchestrationAdaptersTest(unittest.TestCase):
    def test_memory_gateway_maps_scopes_to_filters(self) -> None:
        manager = FakeMemoryManager()
        gateway = MemoryManagerGateway(manager)

        self.assertEqual(gateway.retrieve("tea", "none"), ())
        self.assertEqual(
            gateway.retrieve("tea", "personal_relevant", limit=2),
            ("remembered item",),
        )
        self.assertEqual(
            gateway.retrieve("recipe", "task_relevant_only"),
            ("remembered item",),
        )
        self.assertEqual(
            gateway.retrieve("milk", "list_relevant"),
            ("remembered item",),
        )

        self.assertEqual(manager.retrieve_calls[0]["topic"], None)
        self.assertEqual(manager.retrieve_calls[0]["top_k"], 2)
        self.assertEqual(manager.retrieve_calls[1]["topic"], "task")
        self.assertEqual(manager.retrieve_calls[2]["topic"], "shopping")

    def test_shopping_store_action_uses_shopping_topic(self) -> None:
        manager = FakeMemoryManager()
        gateway = MemoryManagerGateway(manager)
        action = MemoryAction(
            action="store",
            content="Buy oat milk.",
            rationale="User added an item.",
            requires_confirmation=True,
        )

        result = gateway.apply(action, "list_relevant")

        self.assertEqual(result, (True, "stored_successfully"))
        self.assertEqual(
            manager.store_calls,
            [
                {
                    "auto_classify": False,
                    "auto_extract": False,
                    "content": "Buy oat milk.",
                    "layer": "feedback",
                    "memory_key": None,
                    "topic": "shopping",
                    "validate": False,
                }
            ],
        )
        self.assertEqual(manager.process_calls, [])

    def test_non_store_memory_action_delegates_to_manager(self) -> None:
        manager = FakeMemoryManager()
        gateway = MemoryManagerGateway(manager)
        action = MemoryAction(
            action="update",
            content="User likes tea.",
            rationale="Preference.",
            target_key="preference:drink",
            requires_confirmation=True,
        )

        result = gateway.apply(action, "personal_relevant")

        self.assertEqual(result, (True, "processed"))
        self.assertEqual(manager.process_calls, [action])

    def test_speech_gateway_maps_pace_to_length_scale_and_stop(self) -> None:
        tts = FakeTTS()
        gateway = OfflineTTSSpeechGateway(tts)

        self.assertTrue(gateway.speak("hello", "normal"))
        self.assertTrue(gateway.speak("slow hello", "slow"))
        self.assertTrue(gateway.stop())

        self.assertEqual(tts.speak_calls, [("hello", 1.2), ("slow hello", 1.5)])
        self.assertEqual(tts.stop_calls, 1)

    @unittest.skipIf(OfflineTTS is None, "voice output audio dependencies unavailable")
    def test_offline_tts_stop_calls_sounddevice_stop(self) -> None:
        tts = OfflineTTS()

        with patch("voice_concierge.voice_output.tts_pipeline.sd.stop") as stop:
            self.assertTrue(tts.stop())

        stop.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
