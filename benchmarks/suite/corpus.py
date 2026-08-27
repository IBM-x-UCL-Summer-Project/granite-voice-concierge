"""Fixed test material for the benchmark suite.

Kept in one module so a run on one machine is comparable with a run on
another: a benchmark whose corpus differs between operators measures the
corpus as much as the system. Edit deliberately, and note it in the report
when you do.
"""

from __future__ import annotations

# Standard library
from pathlib import Path

from benchmarks.suite.harness import REPO_ROOT

#: The three requests the original whole-pipeline benchmark cycled through,
#: retained so new runs stay comparable with the published figures.
PIPELINE_REQUESTS: tuple[str, ...] = (
    "what is the capital of France",
    "remember that I do not like mushrooms",
    "tell me how to make a cup of tea",
)

#: The command vocabulary the assistant is actually expected to hear. Broader
#: than the pipeline set, because three sentences cannot support a WER figure.
COMMAND_REQUESTS: tuple[str, ...] = (
    "set a timer for ten minutes",
    "remind me to take my medication at eight in the morning",
    "add milk and eggs to my shopping list",
    "what is on my shopping list",
    "start the morning routine",
    "next step",
    "repeat that please",
    "stop",
    "slow down a little",
    "speak faster",
    "switch to cooking mode",
    "switch to driving mode",
    "how many grams are in an ounce",
    "what is the weather like today",
    "delete the reminder about the dentist",
    "tell me what you remember about me",
    "cancel that",
    "what time is it",
    "read my reminders for today",
    "forget that I said that",
)

#: Longer, more conversational phrasing, closer to how an older adult tends to
#: address an assistant than a clipped command does.
CONVERSATIONAL_REQUESTS: tuple[str, ...] = (
    "could you please remind me to call my daughter this evening",
    "I would like to know what is on my shopping list for tomorrow",
    "can you tell me again how long the potatoes need to boil for",
    "sorry, could you say that one more time a bit more slowly",
)

#: Text used to measure synthesis cost. Short, medium and long, because
#: synthesis time scales with output length and one sentence hides that.
SYNTHESIS_TEXTS: tuple[tuple[str, str], ...] = (
    ("short", "Yes, that is done."),
    (
        "medium",
        "I have added milk and eggs to your shopping list. "
        "Would you like me to add anything else?",
    ),
    (
        "long",
        "To make a cup of tea, first boil fresh water in the kettle. "
        "Warm the pot, then add one teaspoon of loose leaves per person. "
        "Pour the water while it is still just off the boil and leave it to "
        "brew for three to five minutes, depending on how strong you like it. "
        "Strain into a cup, and add milk or sugar to taste.",
    ),
)

#: The wake phrase the detector is trained on.
WAKE_PHRASE: str = "hey Jarvis"

#: Phrases chosen to sound like the wake word without being it. Activations on
#: these are the false-positive numerator, so the set is adversarial by design
#: and the resulting rate must never be quoted as a background false-accept rate.
#: A phrase that actually contains the wake word does not belong here: firing
#: on it is correct behaviour, and counting it as a false positive is wrong.
CONFUSABLE_PHRASES: tuple[str, ...] = (
    "hey Harris",
    "hey Travis",
    "hey Marvis",
    "hey Charest",
    "hey Jarred is here",
)

#: Ordinary speech containing no wake word, used to check for spurious
#: activation on neutral content rather than only on near misses.
NEUTRAL_PHRASES: tuple[str, ...] = (
    "the weather has been very changeable this week",
    "I think I left my glasses in the kitchen",
    "there is nothing else I need at the moment",
    "he said he would come round on Thursday afternoon",
    "put the kettle on and we will have a chat",
)

#: Utterances used to exercise voice activity detection boundaries.
VAD_UTTERANCES: tuple[tuple[str, str], ...] = (
    ("short", "what is the time"),
    ("medium", "add milk and eggs to my shopping list"),
    ("long", "could you please remind me to call my daughter this evening"),
)

#: The two halves of an utterance separated by a deliberate pause. They are
#: synthesized separately and joined with constructed silence, so the gap is
#: an exact known length rather than however the voice chooses to render an
#: ellipsis. Sweeping that gap is what locates the cut-off threshold.
VAD_PAUSE_FIRST_HALF: str = "remind me to"
VAD_PAUSE_SECOND_HALF: str = "take my medication"


def recorded_wake_word_clips() -> list[Path]:
    """Recorded older-adult wake-word audio committed to the repository."""
    directory = REPO_ROOT / "experiments/wake-word-detection/test_audio"
    return sorted(directory.glob("*.wav"))
