# tests/unit/app/test_pipeline_streaming.py
# Standard library
from collections.abc import Callable

# Third-party
import numpy as np
import pytest

# Local
from voice_concierge.app.pipeline import (
    VoiceConciergePipeline,
    _StreamingSpeechSink,
)
from voice_concierge.app.reasoning import ReasoningTurnContext, ReasoningTurnResult
from voice_concierge.audio.types import CapturedAudio
from voice_concierge.reasoning.types import ReasoningResponse
from voice_concierge.voice_output.streaming import StreamingSpeaker


class StreamingReasoning:
    """Emits a scripted reply in fragments, as a model would."""

    def __init__(
        self,
        fragments: tuple[str, ...] = ("Beat the eggs well. ", "Serve them at once."),
        *,
        streams: bool = True,
    ) -> None:
        self._fragments = fragments
        self._streams = streams
        self.streamed = False
        self.blocked = False

    def supports_streaming(self) -> bool:
        return self._streams

    def stream_transcript(
        self,
        transcript: str,
        context: ReasoningTurnContext | None = None,
        *,
        on_spoken_text: Callable[[str], None],
    ) -> ReasoningTurnResult:
        self.streamed = True
        for fragment in self._fragments:
            on_spoken_text(fragment)
        return ReasoningTurnResult(
            response=ReasoningResponse(
                spoken_response="".join(self._fragments).strip(),
                confidence="high",
            )
        )

    def process_transcript(
        self,
        transcript: str,
        context: ReasoningTurnContext | None = None,
    ) -> ReasoningTurnResult:
        self.blocked = True
        return ReasoningTurnResult(
            response=ReasoningResponse(
                spoken_response="".join(self._fragments).strip(),
                confidence="high",
            )
        )


class RecordingVoice:
    def __init__(self) -> None:
        self.said: list[str] = []

    def synthesize(self, text: str) -> CapturedAudio:
        self.said.append(text)
        return CapturedAudio(
            samples=np.zeros(2, dtype=np.int16), sample_rate=16000, channels=1
        )


class RecordingPlayer:
    def __init__(self) -> None:
        self.plays = 0

    def play(self, audio: CapturedAudio) -> None:
        self.plays += 1


def _pipeline(reasoning, *, streaming: bool = True):
    voice = RecordingVoice()
    player = RecordingPlayer()
    speaker = StreamingSpeaker(voice, player) if streaming else None
    pipeline = VoiceConciergePipeline(
        reasoning,
        text_to_speech=voice,
        audio_player=player,
        stream_speaker=speaker,
    )
    return pipeline, voice, player


@pytest.mark.unit
class TestStreamingTurn:
    def test_sentences_are_spoken_while_the_model_writes(self) -> None:
        reasoning = StreamingReasoning()
        pipeline, voice, player = _pipeline(reasoning)

        pipeline.process_transcript("how do I make eggs", synthesize=True, play=True)

        assert reasoning.streamed is True
        assert voice.said == ["Beat the eggs well.", "Serve them at once."]
        assert player.plays == 2

    def test_the_reply_is_not_spoken_a_second_time(self) -> None:
        """Finalising would otherwise synthesise the whole reply again."""
        pipeline, voice, _player = _pipeline(StreamingReasoning())

        result = pipeline.process_transcript("hello", synthesize=True, play=True)

        assert len(voice.said) == 2
        assert result.response_audio is None

    def test_the_structured_result_still_comes_back(self) -> None:
        """Memory actions and confirmations depend on it, so it must survive."""
        pipeline, _voice, _player = _pipeline(StreamingReasoning())

        result = pipeline.process_transcript("hello", synthesize=True, play=True)

        assert result.spoken_response == "Beat the eggs well. Serve them at once."
        assert result.reasoning_result is not None


@pytest.mark.unit
class TestFallingBackToBlocking:
    def test_an_engine_that_cannot_stream_uses_the_blocking_path(self) -> None:
        reasoning = StreamingReasoning(streams=False)
        pipeline, voice, _player = _pipeline(reasoning)

        pipeline.process_transcript("hello", synthesize=True, play=True)

        assert reasoning.blocked is True
        assert voice.said == ["Beat the eggs well. Serve them at once."]

    def test_no_speaker_configured_uses_the_blocking_path(self) -> None:
        reasoning = StreamingReasoning()
        pipeline, _voice, _player = _pipeline(reasoning, streaming=False)

        pipeline.process_transcript("hello", synthesize=True, play=True)

        assert reasoning.blocked is True

    def test_a_silent_turn_is_not_streamed(self) -> None:
        """Nothing is being played, so there is nothing to start early."""
        reasoning = StreamingReasoning()
        pipeline, _voice, _player = _pipeline(reasoning)

        pipeline.process_transcript("hello", synthesize=True, play=False)

        assert reasoning.blocked is True


@pytest.mark.unit
class TestSpokenWordCap:
    def test_the_word_cap_still_applies_while_streaming(self) -> None:
        """Driving mode caps replies; speaking early must not bypass that."""
        reasoning = StreamingReasoning(
            fragments=("One two three four five six seven eight nine ten. ",)
        )
        pipeline, voice, _player = _pipeline(reasoning)

        pipeline.process_transcript(
            "switch to driving mode", synthesize=True, play=True
        )

        spoken_words = sum(len(said.split()) for said in voice.said)
        assert spoken_words <= 60


class CountingSpeaker:
    """Stands in for the streaming speaker, recording each sentence."""

    def __init__(self) -> None:
        self.said: list[str] = []

    def speak_stream(self, chunks) -> str:
        text = "".join(chunks)
        self.said.append(text)
        return text


def _sink(max_words: int) -> tuple[_StreamingSpeechSink, CountingSpeaker]:
    speaker = CountingSpeaker()
    return _StreamingSpeechSink(speaker, max_words), speaker


@pytest.mark.unit
class TestStreamingSink:
    def test_whole_sentences_within_budget_are_spoken(self) -> None:
        sink, speaker = _sink(50)

        sink.feed("Beat the eggs. Season them. ")

        assert speaker.said == ["Beat the eggs.", "Season them."]

    def test_the_trailing_sentence_is_flushed(self) -> None:
        """A reply rarely ends in whitespace, so this is the usual last step."""
        sink, speaker = _sink(50)
        sink.feed("Serve at once")

        sink.flush()

        assert speaker.said == ["Serve at once"]

    def test_a_sentence_over_budget_is_trimmed(self) -> None:
        sink, speaker = _sink(3)

        sink.feed("One two three four five six. ")

        assert speaker.said == ["One two three."]

    def test_nothing_is_spoken_once_the_budget_is_gone(self) -> None:
        """Driving mode caps replies; streaming must not talk past it."""
        sink, speaker = _sink(4)

        sink.feed("One two three four. Five six seven eight. ")

        assert speaker.said == ["One two three four."]

    def test_feeding_after_stopping_says_nothing_more(self) -> None:
        sink, speaker = _sink(2)
        sink.feed("One two three. ")

        sink.feed("Four five six. ")

        assert speaker.said == ["One two."]

    def test_flushing_after_stopping_says_nothing_more(self) -> None:
        sink, speaker = _sink(2)
        sink.feed("One two three. ")

        sink.flush()

        assert speaker.said == ["One two."]

    def test_a_budget_exhausted_exactly_stops_the_next_sentence(self) -> None:
        sink, speaker = _sink(4)
        sink.feed("One two three four. ")

        sink.feed("Five six. ")
        sink.flush()

        assert speaker.said == ["One two three four."]

    def test_a_zero_budget_still_says_something(self) -> None:
        """A cap of zero would otherwise make the assistant mute."""
        sink, speaker = _sink(0)

        sink.feed("One two three. ")

        assert speaker.said == ["One."]
