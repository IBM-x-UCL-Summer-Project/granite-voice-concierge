import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from voice_concierge.context import (
    CommandAction,
    ConfirmationIntent,
    ContextManager,
    ContextMode,
    ContextState,
    detect_confirmation_intent,
)
from voice_concierge.context.manager import load_context_state, save_context_state


class ContextManagerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = ContextManager()

    def test_default_state_uses_home_policy(self) -> None:
        state = ContextState()

        decision = self.manager.handle("What did we decide yesterday?", state)

        self.assertEqual(decision.state.mode, "home")
        self.assertEqual(decision.policy.mode, "home")
        self.assertEqual(decision.policy.response_style, "concise_conversational")
        self.assertEqual(decision.policy.memory_scope, "personal_relevant")
        self.assertFalse(decision.mode_changed)

    def test_switches_to_cooking_mode_from_explicit_command(self) -> None:
        state = ContextState()

        decision = self.manager.handle("Please switch to cooking mode", state)

        self.assertEqual(decision.state.mode, "cooking")
        self.assertTrue(decision.mode_changed)
        self.assertEqual(decision.policy.response_style, "step_by_step")
        self.assertEqual(decision.policy.memory_scope, "task_relevant_only")

    def test_negated_mode_commands_do_not_switch_modes(self) -> None:
        examples = (
            "Do not switch to cooking mode",
            "Don't switch to shopping mode",
            "Please do not enter driving mode",
            "Never switch to cooking mode",
        )

        for transcript in examples:
            with self.subTest(transcript=transcript):
                decision = self.manager.handle(transcript, ContextState(mode="home"))

                self.assertEqual(decision.state.mode, "home")
                self.assertIsNone(decision.state.pending_mode)
                self.assertFalse(decision.mode_changed)
                self.assertFalse(decision.needs_confirmation)

    def test_questions_mentioning_modes_do_not_switch_modes(self) -> None:
        examples = (
            "What is cooking mode?",
            "How does shopping mode work?",
            "Can you explain driving mode?",
            "Why would I use home mode?",
        )

        for transcript in examples:
            with self.subTest(transcript=transcript):
                decision = self.manager.handle(
                    transcript,
                    ContextState(mode="home"),
                )

                self.assertEqual(decision.state.mode, "home")
                self.assertIsNone(decision.state.pending_mode)
                self.assertFalse(decision.mode_changed)
                self.assertFalse(decision.needs_confirmation)

    def test_switch_back_phrase_selects_mode_despite_trailing_typo(self) -> None:
        state = ContextState(mode="driving")

        decision = self.manager.handle("Switch back to home mdoe", state)

        self.assertEqual(decision.state.mode, "home")
        self.assertTrue(decision.mode_changed)

    def test_preserves_active_mode_without_new_mode_command(self) -> None:
        state = ContextState(mode="shopping")

        decision = self.manager.handle("Add milk and bread to my list", state)

        self.assertEqual(decision.state.mode, "shopping")
        self.assertFalse(decision.mode_changed)
        self.assertEqual(decision.policy.response_style, "list_focused")

    def test_requires_confirmation_before_entering_driving_mode(self) -> None:
        state = ContextState(mode="home")

        decision = self.manager.handle("Switch to driving mode", state)

        self.assertEqual(decision.state.mode, "home")
        self.assertFalse(decision.mode_changed)
        self.assertTrue(decision.needs_confirmation)
        self.assertEqual(decision.pending_mode, "driving")
        self.assertIn("driving", decision.confirmation_prompt.lower())

    def test_confirming_pending_driving_mode_switches_mode(self) -> None:
        state = ContextState(mode="home", pending_mode="driving")

        decision = self.manager.handle("Yes, confirm", state)

        self.assertEqual(decision.state.mode, "driving")
        self.assertIsNone(decision.state.pending_mode)
        self.assertTrue(decision.mode_changed)
        self.assertEqual(decision.policy.response_style, "very_short_safety_aware")

    def test_cancel_clears_pending_mode_without_switching(self) -> None:
        state = ContextState(mode="home", pending_mode="driving")

        decision = self.manager.handle("Cancel that", state)

        self.assertEqual(decision.state.mode, "home")
        self.assertIsNone(decision.state.pending_mode)
        self.assertEqual(decision.command_action, "cancel")
        self.assertFalse(decision.mode_changed)

    def test_detect_confirmation_intent_classifies_complete_reply(self) -> None:
        examples: dict[str, ConfirmationIntent] = {
            "Yes, go ahead": "confirm",
            "ok please": "confirm",
            "Never mind": "cancel",
            "cancel that": "cancel",
            "what is next": "ambiguous",
            "I know": "ambiguous",
            "not yet": "ambiguous",
            "yesterday": "ambiguous",
            "yes, no": "ambiguous",
        }

        for transcript, expected in examples.items():
            with self.subTest(transcript=transcript):
                self.assertEqual(detect_confirmation_intent(transcript), expected)

    def test_pending_mode_uses_shared_confirmation_intent(self) -> None:
        state = ContextState(mode="home", pending_mode="driving")

        decision = self.manager.handle("ok please", state)

        self.assertEqual(decision.state.mode, "driving")
        self.assertIsNone(decision.state.pending_mode)
        self.assertTrue(decision.mode_changed)

    def test_recognizes_repeat_next_step_and_stop_commands(self) -> None:
        examples: dict[str, CommandAction] = {
            "repeat that": "repeat",
            "what is the next step": "next_step",
            "stop speaking": "stop",
        }

        for transcript, expected_action in examples.items():
            with self.subTest(transcript=transcript):
                decision = self.manager.handle(
                    transcript,
                    ContextState(mode="cooking"),
                )

                self.assertEqual(decision.command_action, expected_action)
                self.assertEqual(decision.state.mode, "cooking")

    def test_negated_stop_phrases_do_not_execute_stop_command(self) -> None:
        examples = (
            "Do not stop",
            "Don't stop speaking",
            "Please do not stop",
        )

        for transcript in examples:
            with self.subTest(transcript=transcript):
                decision = self.manager.handle(
                    transcript,
                    ContextState(mode="cooking"),
                )

                self.assertIsNone(decision.command_action)
                self.assertEqual(decision.state.mode, "cooking")

    def test_updates_accessibility_profile_from_voice_preferences(self) -> None:
        state = ContextState()

        short_decision = self.manager.handle("Keep answers short", state)
        slow_decision = self.manager.handle(
            "Answer more slowly",
            short_decision.state,
        )

        self.assertEqual(short_decision.state.accessibility.verbosity, "short")
        self.assertEqual(slow_decision.state.accessibility.speech_pace, "slow")
        self.assertEqual(slow_decision.policy.max_words, 45)
        self.assertEqual(slow_decision.policy.speech_pace, "slow")

    def test_context_mode_type_allows_mvp_modes(self) -> None:
        modes: tuple[ContextMode, ...] = (
            "home",
            "cooking",
            "shopping",
            "driving",
        )

        self.assertEqual(modes[0], "home")

    def test_speaking_pace_persistence(self) -> None:
        """Regression test for Issue #38: Speaking pace persistence."""
        decision = self.manager.handle("Answer more slowly", ContextState())

        save_context_state(decision.state)

        loaded_state = load_context_state()
        self.assertEqual(loaded_state.accessibility.speech_pace, "slow")

        test_file_path = ".voice_concierge_state.json"
        if os.path.exists(test_file_path):
            os.remove(test_file_path)

    def test_confirmation_substring_collision_regression(self) -> None:
        """Regression test for Issue #35: Substring-based confirmation."""
        from dataclasses import replace

        base_state = ContextState(mode="home")
        pending_state = replace(base_state, pending_mode="driving")

        # 1.  (Deliberate confirmation)
        decision = self.manager.handle("yes, please do it", pending_state)
        self.assertEqual(decision.state.mode, "driving")
        self.assertIsNone(decision.state.pending_mode)
        self.assertEqual(decision.confirmation_prompt, "")

        # 2.  (Deliberate cancellation)
        decision = self.manager.handle("no stop", pending_state)
        self.assertEqual(decision.state.mode, "home")
        self.assertIsNone(decision.state.pending_mode)
        self.assertEqual(decision.confirmation_prompt, "")

        # 3.  (Substring collision for 'yes')
        decision = self.manager.handle("I mentioned that yesterday", pending_state)
        self.assertTrue(decision.needs_confirmation)
        self.assertEqual(decision.confirmation_prompt, "Sorry, was that a yes or a no?")
        self.assertEqual(decision.state.pending_mode, "driving")

        # 4.  (Substring collision for 'no')
        decision = self.manager.handle("I know", pending_state)
        self.assertTrue(decision.needs_confirmation)
        self.assertEqual(decision.confirmation_prompt, "Sorry, was that a yes or a no?")
        self.assertEqual(decision.state.pending_mode, "driving")


if __name__ == "__main__":
    unittest.main()
