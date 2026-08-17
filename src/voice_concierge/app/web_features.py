"""Browser-specific orchestration for local features outside the turn pipeline."""

from __future__ import annotations

import logging
import re
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock

from voice_concierge.app.pipeline import VoiceConciergePipeline
from voice_concierge.app.reminders import ReminderTurnHandler
from voice_concierge.app.serialization import (
    app_turn_result_to_dict,
    captured_audio_to_dict,
)
from voice_concierge.app.types import (
    AppPipelineState,
    AppTurnOptions,
    TextToSpeechAdapter,
)
from voice_concierge.command_control.transcript_parser import TranscriptCommandParser
from voice_concierge.command_control.types import CommandEvent
from voice_concierge.privacy.centre import PrivacyCentre
from voice_concierge.privacy.disclosure import build_report
from voice_concierge.privacy.types import StoredMemory
from voice_concierge.routines.adapter import RoutineCommandAdapter
from voice_concierge.routines.intent import is_routine_request
from voice_concierge.routines.runner import (
    CONFIRM_PROMPTS,
    CONFIRMATION_WORDS,
    DEFAULT_AUTO_ADVANCE_DELAY,
    DEFAULT_IDLE_TIMEOUT,
)
from voice_concierge.scheduling.runner import ReminderRunner
from voice_concierge.scheduling.types import Reminder

MAX_ROUTINE_SESSIONS = 32
MAX_DUE_NOTIFICATIONS = 64
LOGGER = logging.getLogger("voice_concierge.web.features")
_SAFETY_INTERRUPT = re.compile(
    r"\b(?:emergency|gas\s+leak|smell\s+gas|fire|smoke|can't\s+breathe|"
    r"cannot\s+breathe|chest\s+pain|severe\s+bleeding|in\s+danger)\b",
    flags=re.IGNORECASE,
)


class WebReminderNotifier:
    """Queue due reminders until the local browser acknowledges displaying them."""

    def __init__(
        self,
        text_to_speech: TextToSpeechAdapter | None = None,
        *,
        max_notifications: int = MAX_DUE_NOTIFICATIONS,
    ) -> None:
        self._text_to_speech = text_to_speech
        self._max_notifications = max_notifications
        self._notifications: deque[dict[str, object]] = deque()
        self._lock = RLock()

    def notify(self, reminder: Reminder) -> None:
        notification = reminder_to_dict(reminder, due=True)
        if self._text_to_speech is not None:
            try:
                notification["audio"] = captured_audio_to_dict(
                    self._text_to_speech.synthesize(reminder.announcement)
                )
            except Exception:
                notification["audio"] = None
        with self._lock:
            if len(self._notifications) >= self._max_notifications:
                raise RuntimeError("The browser reminder queue is full.")
            self._notifications.append(notification)

    def drain(self) -> list[dict[str, object]]:
        """Return queued announcements exactly once."""

        with self._lock:
            notifications = list(self._notifications)
            self._notifications.clear()
            return notifications

    def collect(self, check_due: Callable[[], object]) -> list[dict[str, object]]:
        """Check once immediately, then return queued announcements."""

        check_due()
        return self.drain()


@dataclass
class _WebRoutineSession:
    adapter: RoutineCommandAdapter
    pending_command: CommandEvent | None = None
    pace_delta: float | None = None


class WebRoutineSessions:
    """Keep one interactive routine adapter per authoritative web session."""

    def __init__(
        self,
        adapter_factory: Callable[[], RoutineCommandAdapter],
        *,
        max_sessions: int = MAX_ROUTINE_SESSIONS,
    ) -> None:
        self._adapter_factory = adapter_factory
        self._max_sessions = max_sessions
        self._sessions: OrderedDict[str, _WebRoutineSession] = OrderedDict()
        self._parser = TranscriptCommandParser()

    def route(self, session_id: str, transcript: str) -> str | None:
        """Return a routine response, or None when this is an ordinary turn."""

        session = self._sessions.get(session_id)
        if session is not None:
            self._sessions.move_to_end(session_id)
            if _SAFETY_INTERRUPT.search(transcript):
                return None
            adapter = session.adapter
            if adapter.awaiting_choice:
                return self._keep_or_finish(
                    session_id, adapter.resolve_choice(transcript)
                )
            if adapter.status in {"running", "paused"}:
                event = self._parser.parse(transcript)
                if session.pending_command is not None:
                    return self._resolve_confirmation(session_id, event)
                if event is None:
                    return None
                if event.command in CONFIRMATION_WORDS:
                    return "There isn't a routine command to confirm."
                if event.command == "back":
                    session.pending_command = event
                    return CONFIRM_PROMPTS["back"]
                if event.command in {"slower", "faster"}:
                    session.pace_delta = -0.1 if event.command == "slower" else 0.1
                    event = CommandEvent(command="repeat", phrase="(pace changed)")
                return self._keep_or_finish(session_id, adapter.handle_command(event))
            self._sessions.pop(session_id, None)

        if not is_routine_request(transcript):
            return None
        try:
            adapter = self._adapter_factory()
        except Exception:
            return "I couldn't load guided routines right now."
        self._sessions[session_id] = _WebRoutineSession(adapter)
        self._trim()
        return self._keep_or_finish(session_id, adapter.start_routine(transcript))

    def reset(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def snapshot(self, session_id: str) -> dict[str, object]:
        """Return browser control metadata without exposing routine internals."""

        session = self._sessions.get(session_id)
        if session is None:
            return {
                "active": False,
                "status": None,
                "awaiting_choice": False,
                "awaiting_confirmation": False,
            }
        adapter = session.adapter
        active = adapter.awaiting_choice or adapter.status in {"running", "paused"}
        snapshot: dict[str, object] = {
            "active": active,
            "status": adapter.status,
            "awaiting_choice": adapter.awaiting_choice,
            "awaiting_confirmation": session.pending_command is not None,
            "auto_advance_seconds": DEFAULT_AUTO_ADVANCE_DELAY,
            "paused_idle_seconds": DEFAULT_IDLE_TIMEOUT,
        }
        if session.pace_delta is not None:
            snapshot["pace_delta"] = session.pace_delta
            session.pace_delta = None
        return snapshot

    def _resolve_confirmation(
        self,
        session_id: str,
        event: CommandEvent | None,
    ) -> str:
        session = self._sessions[session_id]
        if event is None or event.command not in CONFIRMATION_WORDS:
            return "Sorry, was that a yes or a no?"
        pending = session.pending_command
        session.pending_command = None
        if event.command == "no" or pending is None:
            return "Okay, staying on this step."
        return self._keep_or_finish(
            session_id,
            session.adapter.handle_command(pending),
        )

    def _keep_or_finish(self, session_id: str, response: str) -> str:
        session = self._sessions.get(session_id)
        adapter = session.adapter if session is not None else None
        if (
            adapter is not None
            and not adapter.awaiting_choice
            and session.pending_command is None
            and adapter.status
            not in {
                "running",
                "paused",
            }
        ):
            self._sessions.pop(session_id, None)
        return response

    def _trim(self) -> None:
        while len(self._sessions) > self._max_sessions:
            self._sessions.popitem(last=False)


@dataclass
class WebFeatureServices:
    """Optional local services connected to the browser application."""

    reminder_handler: ReminderTurnHandler | None = None
    privacy_centre: PrivacyCentre | None = None
    routine_sessions: WebRoutineSessions | None = None
    reminder_notifier: WebReminderNotifier | None = None
    reminder_runner: ReminderRunner | None = None

    @property
    def capabilities(self) -> dict[str, bool]:
        return {
            "reminders": self.reminder_handler is not None,
            "guided_routines": self.routine_sessions is not None,
            "privacy_centre": self.privacy_centre is not None,
        }

    def start(self) -> None:
        """Start due-reminder checks as soon as the Web application starts."""

        if self.reminder_runner is not None:
            self.reminder_runner.start()

    def close(self) -> None:
        if self.reminder_runner is not None:
            self.reminder_runner.stop()
        if self.reminder_handler is not None:
            self.reminder_handler.close()

    def reset_session(self, session_id: str) -> None:
        if self.routine_sessions is not None:
            self.routine_sessions.reset(session_id)

    def routine_snapshot(self, session_id: str) -> dict[str, object]:
        if self.routine_sessions is None:
            return {"active": False}
        return self.routine_sessions.snapshot(session_id)

    def due_notifications(self) -> list[dict[str, object]]:
        """Deliver due reminders into the browser request that collected them."""

        if self.reminder_notifier is None or self.reminder_runner is None:
            return []
        if self.reminder_runner.running:
            return self.reminder_notifier.drain()
        return self.reminder_notifier.collect(self.reminder_runner.check_now)

    def route_transcript(
        self,
        pipeline: VoiceConciergePipeline,
        session_id: str,
        transcript: str,
        state: AppPipelineState | None,
        options: AppTurnOptions,
        *,
        record_conversation: bool = True,
    ) -> dict[str, object] | None:
        """Run an integrated feature turn before falling through to reasoning."""

        current_state = state or AppPipelineState()
        if (
            current_state.pending_memory_action is not None
            or current_state.pending_bulk_memory_delete
            or current_state.context.pending_mode is not None
        ):
            LOGGER.debug(
                "web_feature_route session_id=%s route=pipeline_pending transcript=%r",
                session_id,
                transcript,
            )
            return None

        response: str | None = None
        route: str | None = None
        if self.routine_sessions is not None:
            response = self.routine_sessions.route(session_id, transcript)
            if response is not None:
                route = "guided_routine"
        if response is None and self.reminder_handler is not None:
            if self.reminder_handler.handles(transcript):
                response = self.reminder_handler.run(transcript)
                route = "reminder"
        if response is None and self.privacy_centre is not None:
            if _is_privacy_summary_request(transcript):
                report = build_report(self.privacy_centre)
                response = (
                    f"You have {report.memory_count} saved "
                    f"{'memory' if report.memory_count == 1 else 'memories'} on this "
                    "device. Recorded audio and conversation history are not stored. "
                    "Open Local data to review or change saved memories."
                )
                route = "privacy_summary"
        if response is None:
            return None

        LOGGER.debug(
            "web_feature_route session_id=%s route=%s transcript=%r response=%r",
            session_id,
            route,
            transcript,
            response,
        )

        result = pipeline.process_local_response(
            transcript,
            response,
            current_state,
            synthesize=options.synthesize,
            play=options.play,
            response_length=options.response_length,
            record_conversation=record_conversation,
        )
        return app_turn_result_to_dict(result)


def reminder_to_dict(reminder: Reminder, *, due: bool = False) -> dict[str, object]:
    return {
        "id": reminder.identifier,
        "text": reminder.text,
        "kind": reminder.kind,
        "due_at": reminder.due_at,
        "due": reminder.due_display(),
        "recurrence": reminder.schedule.recurrence,
        "interval_seconds": reminder.schedule.interval_seconds,
        "weekday": reminder.schedule.weekday,
        "announcement": reminder.announcement if due else None,
    }


def stored_memory_to_dict(memory: StoredMemory) -> dict[str, object]:
    """Serialize the stable PrivacyCentre view without exposing database internals."""

    return {
        "id": memory.identifier,
        "content": memory.content,
        "layer": memory.layer,
        "layer_description": memory.layer_description,
        "revision": memory.revision,
        "created_at": memory.created_at,
        "created": memory.created_display,
        "topic": memory.topic,
        "person": memory.person,
        "source_type": memory.source_type,
    }


def privacy_report_to_dict(centre: PrivacyCentre) -> dict[str, object]:
    report = build_report(centre)
    return {
        "memory_count": report.memory_count,
        "counts_by_layer": report.counts_by_layer,
        "locations": [
            {
                "name": location.name,
                "path": location.path,
                "description": location.description,
                "exists": location.exists,
                "size_bytes": location.size_bytes,
                "size": location.size_display,
            }
            for location in report.locations
        ],
        "not_retained": list(report.not_retained),
        "memories": [
            stored_memory_to_dict(memory) for memory in centre.list_memories()
        ],
    }


def _is_privacy_summary_request(transcript: str) -> bool:
    text = " ".join(transcript.casefold().split())
    phrases = (
        "privacy centre",
        "privacy center",
        "what information do you store",
        "what do you store about me",
        "where is my data",
        "where do you keep my data",
        "explain your privacy",
        "explain local storage",
    )
    return any(phrase in text for phrase in phrases)
