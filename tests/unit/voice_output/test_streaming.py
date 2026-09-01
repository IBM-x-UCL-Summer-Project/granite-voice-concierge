# tests/unit/voice_output/test_streaming.py
# Standard library
from collections.abc import Iterator

# Third-party
import numpy as np
import pytest

# Local
from voice_concierge.audio.types import CapturedAudio
from voice_concierge.voice_output.streaming import (
    Player,
    StreamingSpeaker,
    Synthesizer,
)


class RecordingSynthesizer:
    """Records what it was asked to say."""

    def __init__(self, *, fail_on: str | None = None) -> None:
        self.spoken: list[str] = []
        self._fail_on = fail_on

    def synthesize(self, text: str) -> CapturedAudio:
        if text == self._fail_on:
            raise RuntimeError("no voice available")
        self.spoken.append(text)
        return CapturedAudio(
            samples=np.zeros(2, dtype=np.int16), sample_rate=16000, channels=1
        )


class RecordingPlayer:
    """Records what it was asked to play."""

    def __init__(self, *, fail: bool = False) -> None:
        self.plays = 0
        self._fail = fail

    def play(self, audio: CapturedAudio) -> None:
        if self._fail:
            raise RuntimeError("device gone")
        self.plays += 1


def _speaker(
    **kwargs,
) -> tuple[StreamingSpeaker, RecordingSynthesizer, RecordingPlayer]:
    tts = kwargs.pop("tts", None) or RecordingSynthesizer()
    player = kwargs.pop("player", None) or RecordingPlayer()
    return StreamingSpeaker(tts, player, **kwargs), tts, player


@pytest.mark.unit
class TestConformance:
    def test_fakes_satisfy_the_protocols(self) -> None:
        assert isinstance(RecordingSynthesizer(), Synthesizer)
        assert isinstance(RecordingPlayer(), Player)


@pytest.mark.unit
class TestSpeaking:
    def test_each_sentence_is_spoken_separately(self) -> None:
        """Speaking per sentence is what removes the wait for the full reply."""
        speaker, tts, player = _speaker()

        speaker.speak_stream(["Beat the eggs well. ", "Season them lightly."])

        assert tts.spoken == ["Beat the eggs well.", "Season them lightly."]
        assert player.plays == 2

    def test_the_full_reply_is_returned_for_the_transcript(self) -> None:
        speaker, _tts, _player = _speaker()

        spoken = speaker.speak_stream(["Beat the eggs. ", "Serve at once."])

        assert spoken == "Beat the eggs. Serve at once."

    def test_sentences_are_spoken_in_order(self) -> None:
        speaker, tts, _player = _speaker()

        speaker.speak_stream(["One moment please. ", "Two moments please. "])

        assert tts.spoken == ["One moment please.", "Two moments please."]

    def test_an_empty_stream_says_nothing(self) -> None:
        speaker, tts, player = _speaker()

        assert speaker.speak_stream([]) == ""
        assert tts.spoken == []
        assert player.plays == 0

    def test_a_trailing_sentence_without_punctuation_is_still_spoken(self) -> None:
        speaker, tts, _player = _speaker()

        speaker.speak_stream(["Serve them straight away"])

        assert tts.spoken == ["Serve them straight away"]


@pytest.mark.unit
class TestSpeakingAsItArrives:
    def test_speech_begins_before_the_stream_has_finished(self) -> None:
        """The whole point: the user hears sentence one while two is written."""
        tts = RecordingSynthesizer()
        speaker, _tts, _player = _speaker(tts=tts)
        generated: list[str] = []

        def tokens() -> Iterator[str]:
            for token in ["Beat the eggs well. ", "Season them lightly. "]:
                # Whatever has been spoken by the time this token is pulled.
                generated.append(",".join(tts.spoken))
                yield token

        speaker.speak_stream(tokens())

        # Nothing spoken before the first token, sentence one spoken before the
        # second was ever generated.
        assert generated == ["", "Beat the eggs well."]


@pytest.mark.unit
class TestFailures:
    def test_a_sentence_that_cannot_be_synthesised_does_not_stop_the_rest(
        self,
    ) -> None:
        """The user has already heard the start; stopping leaves it wrong."""
        tts = RecordingSynthesizer(fail_on="Season them lightly.")
        speaker, _tts, player = _speaker(tts=tts)

        spoken = speaker.speak_stream(
            ["Beat the eggs well. ", "Season them lightly. ", "Serve at once. "]
        )

        assert tts.spoken == ["Beat the eggs well.", "Serve at once."]
        assert player.plays == 2
        # The returned text is what was meant to be said, not what got through.
        assert "Season them lightly." in spoken

    def test_a_dead_player_does_not_stop_the_reply(self) -> None:
        speaker, tts, _player = _speaker(player=RecordingPlayer(fail=True))

        spoken = speaker.speak_stream(["Beat the eggs well. ", "Serve at once."])

        assert spoken == "Beat the eggs well. Serve at once."


@pytest.mark.unit
class TestObservation:
    def test_each_sentence_is_announced_before_it_is_spoken(self) -> None:
        seen: list[str] = []
        speaker, _tts, _player = _speaker(on_sentence=seen.append)

        speaker.speak_stream(["Beat the eggs well. ", "Serve at once."])

        assert seen == ["Beat the eggs well.", "Serve at once."]

    def test_a_failing_sentence_is_still_announced(self) -> None:
        seen: list[str] = []
        tts = RecordingSynthesizer(fail_on="Serve at once.")
        speaker, _tts, _player = _speaker(tts=tts, on_sentence=seen.append)

        speaker.speak_stream(["Beat the eggs well. ", "Serve at once."])

        assert seen == ["Beat the eggs well.", "Serve at once."]


@pytest.mark.unit
class TestThresholds:
    def test_the_sentence_threshold_is_passed_through(self) -> None:
        speaker, tts, _player = _speaker(min_chars=0)

        speaker.speak_stream(["Yes. No. "])

        assert tts.spoken == ["Yes.", "No."]
