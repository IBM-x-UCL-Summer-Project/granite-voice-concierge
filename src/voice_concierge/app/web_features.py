"""Browser-specific orchestration for local features outside the turn pipeline."""

from __future__ import annotations

import re
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock

from voice_concierge.app.pipeline import VoiceConciergePipeline
from voice_concierge.app.reminders import ReminderTurnHandler
from voice_concierge.app.serialization import app_turn_result_to_dict
from voice_concierge.app.types import AppPipelineState, AppTurnOptions
from voice_concierge.command_control.transcript_parser import TranscriptCommandParser
from voice_concierge.privacy.centre import PrivacyCentre
from voice_concierge.privacy.disclosure import build_report
from voice_concierge.privacy.types import StoredMemory
from voice_concierge.routines.adapter import RoutineCommandAdapter
from voice_concierge.routines.intent import is_routine_request
from voice_concierge.scheduling.runner import ReminderRunner
from voice_concierge.scheduling.types import Reminder

MAX_ROUTINE_SESSIONS = 32
MAX_DUE_NOTIFICATIONS = 64
_SAFETY_INTERRUPT = re.compile(
    r"\b(?:emergency|gas\s+leak|smell\s+gas|fire|smoke|can't\s+breathe|"
    r"cannot\s+breathe|chest\s+pain|severe\s+bleeding|in\s+danger)\b",
    flags=re.IGNORECASE,
)


class WebReminderNotifier:
    """Queue due reminders until the local browser acknowledges displaying them."""

    def __init__(self, *, max_notifications: int = MAX_DUE_NOTIFICATIONS) -> None:
        self._notifications: deque[dict[str, object]] = deque(maxlen=max_notifications)
        self._lock = RLock()
        self._accepting = False

    def notify(self, reminder: Reminder) -> None:
        with self._lock:
            if not self._accepting:
                raise RuntimeError("No browser is currently collecting reminders.")
            self._notifications.append(reminder_to_dict(reminder, due=True))

    def drain(self) -> list[dict[str, object]]:
        """Return queued announcements exactly once."""

        with self._lock:
            notifications = list(self._notifications)
            self._notifications.clear()
            return notifications

    def collect(self, check_due: Callable[[], object]) -> list[dict[str, object]]:
        """Accept delivery only while a browser request can receive it."""

        with self._lock:
            self._accepting = True
            try:
                check_due()
            finally:
                self._accepting = False
            return self.drain()


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
        self._adapters: OrderedDict[str, RoutineCommandAdapter] = OrderedDict()
        self._parser = TranscriptCommandParser()

    def route(self, session_id: str, transcript: str) -> str | None:
        """Return a routine response, or None when this is an ordinary turn."""

        adapter = self._adapters.get(session_id)
        if adapter is not None:
            self._adapters.move_to_end(session_id)
            if _SAFETY_INTERRUPT.search(transcript):
                return None
            if adapter.awaiting_choice:
                return self._keep_or_finish(
                    session_id, adapter.resolve_choice(transcript)
                )
            if adapter.status in {"running", "paused"}:
                event = self._parser.parse(transcript)
                if event is None or event.command in {"yes", "no", "slower", "faster"}:
                    return None
                return self._keep_or_finish(session_id, adapter.handle_command(event))
            self._adapters.pop(session_id, None)

        if not is_routine_request(transcript):
            return None
        try:
            adapter = self._adapter_factory()
        except Exception:
            return "I couldn't load guided routines right now."
        self._adapters[session_id] = adapter
        self._trim()
        return self._keep_or_finish(session_id, adapter.start_routine(transcript))

    def reset(self, session_id: str) -> None:
        self._adapters.pop(session_id, None)

    def _keep_or_finish(self, session_id: str, response: str) -> str:
        adapter = self._adapters.get(session_id)
        if (
            adapter is not None
            and not adapter.awaiting_choice
            and adapter.status
            not in {
                "running",
                "paused",
            }
        ):
            self._adapters.pop(session_id, None)
        return response

    def _trim(self) -> None:
        while len(self._adapters) > self._max_sessions:
            self._adapters.popitem(last=False)


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
        """Feature lifecycle hook; due reminders are pulled by the browser."""

    def close(self) -> None:
        if self.reminder_runner is not None:
            self.reminder_runner.stop()
        if self.reminder_handler is not None:
            self.reminder_handler.close()

    def reset_session(self, session_id: str) -> None:
        if self.routine_sessions is not None:
            self.routine_sessions.reset(session_id)

    def due_notifications(self) -> list[dict[str, object]]:
        """Deliver due reminders into the browser request that collected them."""

        if self.reminder_notifier is None or self.reminder_runner is None:
            return []
        return self.reminder_notifier.collect(self.reminder_runner.check_now)

    def route_transcript(
        self,
        pipeline: VoiceConciergePipeline,
        session_id: str,
        transcript: str,
        state: AppPipelineState | None,
        options: AppTurnOptions,
    ) -> dict[str, object] | None:
        """Run an integrated feature turn before falling through to reasoning."""

        current_state = state or AppPipelineState()
        if (
            current_state.pending_memory_action is not None
            or current_state.context.pending_mode is not None
        ):
            return None

        response: str | None = None
        if self.routine_sessions is not None:
            response = self.routine_sessions.route(session_id, transcript)
        if response is None and self.reminder_handler is not None:
            if self.reminder_handler.handles(transcript):
                response = self.reminder_handler.run(transcript)
        if response is None and self.privacy_centre is not None:
            if _is_privacy_summary_request(transcript):
                report = build_report(self.privacy_centre)
                response = (
                    f"You have {report.memory_count} saved "
                    f"{'memory' if report.memory_count == 1 else 'memories'} on this "
                    "device. Recorded audio and conversation history are not stored. "
                    "Open Local data to review or change saved memories."
                )
        if response is None:
            return None

        result = pipeline.process_local_response(
            transcript,
            response,
            current_state,
            synthesize=options.synthesize,
            play=options.play,
            response_length=options.response_length,
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
