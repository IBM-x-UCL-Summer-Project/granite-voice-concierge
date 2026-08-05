"""Tests for Granite prompt construction."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from voice_concierge.reasoning import (
    DEFAULT_PROMPT_VERSION,
    ChatMessage,
    PromptTemplateError,
    ReasoningConstraints,
    ReasoningRequest,
    build_granite_messages,
    load_prompt_template,
)
from voice_concierge.reasoning.prompting import (
    _MAX_SUMMARY_CHARS,
    _MAX_TRANSCRIPT_CHARS,
    _format_conversation_summary,
    _format_transcript,
)


def test_chat_message_serializes_to_runner_dict() -> None:
    message = ChatMessage(role="user", content="Hello")

    assert message.as_dict() == {"role": "user", "content": "Hello"}


def test_default_prompt_template_loads_versioned_resources() -> None:
    prompt = load_prompt_template()

    assert DEFAULT_PROMPT_VERSION == "v2"
    assert prompt.prompt_id == "local-reasoning"
    assert prompt.version == "v2"
    assert prompt.default_mode == "home"
    assert set(prompt.mode_policies) == {"cooking", "driving", "home", "shopping"}


def test_unknown_prompt_template_version_is_rejected() -> None:
    with pytest.raises(PromptTemplateError, match="is not available"):
        load_prompt_template("missing-version")


def test_granite_messages_include_offline_policy() -> None:
    request = ReasoningRequest(transcript="Search online for today's news.")

    messages = build_granite_messages(request)

    assert [message.role for message in messages] == ["system", "user"]
    system_prompt = messages[0].content
    assert "no internet or cloud service" in system_prompt
    assert "stable public facts" in system_prompt
    assert "built-in general knowledge" in system_prompt
    assert "cannot verify up-to-date information offline" in system_prompt
    assert "Do not claim to browse" in system_prompt
    assert "Ask for explicit confirmation" in system_prompt
    assert "Structured output examples" in system_prompt


def test_granite_messages_include_mode_and_memory_context() -> None:
    request = ReasoningRequest(
        transcript="How do I like you to answer?",
        mode="cooking",
        memories=("User prefers short answers.",),
        conversation_summary="User was preparing breakfast.",
        constraints=ReasoningConstraints(max_words=30),
    )

    messages = build_granite_messages(request)

    assert "Cooking mode" in messages[0].content
    assert "Maximum spoken response length: 30 words." in messages[0].content
    user_prompt = messages[1].content
    assert "Active mode: cooking" in user_prompt
    assert "- User prefers short answers." in user_prompt
    assert "User was preparing breakfast." in user_prompt
    assert "How do I like you to answer?" in user_prompt
    assert "Return only a JSON object" in user_prompt


def test_granite_system_prompt_includes_memory_action_examples() -> None:
    request = ReasoningRequest(transcript="Remember that I prefer short answers.")

    messages = build_granite_messages(request)

    system_prompt = messages[0].content
    assert "Who was Anne Frank?" in system_prompt
    assert "When is the next GTA game coming out?" in system_prompt
    assert '"action":"store"' in system_prompt
    assert '"action":"update"' in system_prompt
    assert "do not invent list items" in system_prompt


def test_granite_messages_mark_missing_memory_context() -> None:
    request = ReasoningRequest(transcript="What did we decide last week?")

    messages = build_granite_messages(request)

    assert "No local memories supplied." in messages[1].content
    assert "No summary supplied." in messages[1].content


def test_granite_messages_reject_invalid_prompt_version() -> None:
    request = ReasoningRequest(transcript="Hello")

    with pytest.raises(PromptTemplateError, match="is invalid"):
        build_granite_messages(request, prompt_version="../outside")


def test_transcript_truncation() -> None:
    """Ensure oversized transcripts are truncated at the end."""
    # 1. normal length
    short_text = "Hello, what is the weather?"
    assert _format_transcript(short_text) == short_text

    # 2. exceed
    long_text = "A" * (_MAX_TRANSCRIPT_CHARS + 100)
    result = _format_transcript(long_text)

    assert result.endswith("... [truncated]")
    assert result.startswith("A" * _MAX_TRANSCRIPT_CHARS)
    assert len(result) == _MAX_TRANSCRIPT_CHARS + len("... [truncated]")


def test_summary_truncation() -> None:
    """Ensure oversized history summaries are truncated at the beginning."""
    #  Mock  ReasoningRequest
    mock_request = Mock()

    #
    mock_request.conversation_summary = None
    assert _format_conversation_summary(mock_request) == "No summary supplied."

    #
    mock_request.conversation_summary = "User asked for weather. Assistant replied."
    assert (
        _format_conversation_summary(mock_request)
        == mock_request.conversation_summary
    )

    #
    long_summary = "B" * (_MAX_SUMMARY_CHARS + 100)
    mock_request.conversation_summary = long_summary
    result = _format_conversation_summary(mock_request)

    assert result.startswith("... [truncated]\n")
    assert result.endswith("B" * _MAX_SUMMARY_CHARS)
    assert len(result) == _MAX_SUMMARY_CHARS + len("... [truncated]\n")
