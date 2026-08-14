"""Command-line reminders and timers.

The typed surface over ReminderService, and the way to check what is set without
starting the whole assistant. It renders and confirms; every rule about times
and repeats lives in the service and the parser, so the voice path and this one
cannot disagree about what a request means.

    python -m voice_concierge.scheduling                       # what is set
    python -m voice_concierge.scheduling add "remind me to stretch in 10 minutes"
    python -m voice_concierge.scheduling cancel 3
    python -m voice_concierge.scheduling clear
    python -m voice_concierge.scheduling watch     # announce as they fall due
"""

# Standard library
import argparse
import sys
from collections.abc import Callable, Sequence
from typing import TextIO

# Local
from voice_concierge.scheduling.errors import SchedulingError
from voice_concierge.scheduling.factory import build_reminder_service
from voice_concierge.scheduling.recurrence import describe_delay, seconds_until
from voice_concierge.scheduling.runner import PrintNotifier, ReminderRunner
from voice_concierge.scheduling.service import ReminderService
from voice_concierge.scheduling.types import Reminder

CONFIRM_WORD = "CLEAR"  # typed in full before every reminder is removed


def format_reminder(reminder: Reminder, *, now: int) -> str:
    """Render one reminder with when it is next due."""
    identifier = reminder.identifier if reminder.identifier is not None else "?"
    delay = describe_delay(seconds_until(reminder.due_at, now))
    repeat = (
        f", repeats {reminder.schedule.recurrence}" if reminder.schedule.repeats else ""
    )
    return (
        f"[{identifier}] {reminder.text} - {reminder.due_display()} "
        f"(in {delay}{repeat})"
    )


def show_list(service: ReminderService, *, stdout: TextIO) -> int:
    """List everything still set, soonest first."""
    now = service.now()
    reminders = service.upcoming()
    if not reminders:
        print("Nothing is set.", file=stdout)
        return 0
    for reminder in reminders:
        print(format_reminder(reminder, now=now), file=stdout)
    print(f"\n{len(reminders)} set.", file=stdout)
    return 0


def run_add(service: ReminderService, request: str, *, stdout: TextIO) -> int:
    """Create a reminder from a spoken-style request."""
    reminder = service.create_from_speech(request)
    print(service.confirmation(reminder), file=stdout)
    return 0 if reminder is not None else 1


def run_cancel(service: ReminderService, identifier: int, *, stdout: TextIO) -> int:
    """Remove one reminder."""
    service.cancel(identifier)
    print("Cancelled.", file=stdout)
    return 0


def run_clear(
    service: ReminderService,
    *,
    assume_yes: bool,
    confirm: Callable[[str], str],
    stdout: TextIO,
) -> int:
    """Remove every reminder, after an explicit typed confirmation."""
    total = len(service.upcoming())
    if total == 0:
        print("Nothing is set, so there is nothing to clear.", file=stdout)
        return 0
    if not assume_yes:
        print(f"This removes all {total} reminders. It cannot be undone.", file=stdout)
        if confirm(f"Type {CONFIRM_WORD} to confirm: ").strip() != CONFIRM_WORD:
            print("Left unchanged.", file=stdout)
            return 0
    print(f"Removed {service.cancel_all()} reminders.", file=stdout)
    return 0


def run_watch(
    service: ReminderService,
    *,
    once: bool,
    wait: Callable[[], None],
    stdout: TextIO,
) -> int:
    """Announce reminders as they come due.

    Delivers anything already overdue straight away, including reminders missed
    while nothing was running, then keeps watching until interrupted.
    """
    runner = ReminderRunner(
        service, PrintNotifier(lambda line: print(line, file=stdout))
    )
    delivered = runner.check_now()
    if not delivered:
        print("Nothing due.", file=stdout)
    if once:
        return 0
    print("Watching for reminders. Press Ctrl+C to stop.", file=stdout)
    runner.start()
    try:
        wait()
    except KeyboardInterrupt:
        print("\nStopped watching.", file=stdout)
    finally:
        runner.stop()
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    service: ReminderService | None = None,
    confirm: Callable[[str], str] = input,
    wait: Callable[[], None] | None = None,
    stdout: TextIO = sys.stdout,
) -> int:
    """Run the reminder command line."""
    args = _build_parser().parse_args(argv)
    active = service if service is not None else build_reminder_service()
    try:
        return _dispatch(args, active, confirm=confirm, wait=wait, stdout=stdout)
    except SchedulingError as exc:
        # Fail loudly: a reminder that was not set must never look like one
        # that was.
        print(f"Could not do that: {exc}", file=stdout)
        return 1


def _dispatch(
    args: argparse.Namespace,
    service: ReminderService,
    *,
    confirm: Callable[[str], str],
    wait: Callable[[], None] | None,
    stdout: TextIO,
) -> int:
    """Route a parsed command to its handler."""
    if args.command == "add":
        return run_add(service, args.request, stdout=stdout)
    if args.command == "cancel":
        return run_cancel(service, args.id, stdout=stdout)
    if args.command == "clear":
        return run_clear(service, assume_yes=args.yes, confirm=confirm, stdout=stdout)
    if args.command == "watch":
        return run_watch(
            service, once=args.once, wait=wait or _sleep_forever, stdout=stdout
        )
    return show_list(service, stdout=stdout)


def _sleep_forever() -> None:  # pragma: no cover - blocks until interrupted
    """Block until the user interrupts, while the runner works in background."""
    import threading

    threading.Event().wait()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m voice_concierge.scheduling",
        description="Set, review and cancel local reminders and timers.",
    )
    commands = parser.add_subparsers(dest="command")

    adding = commands.add_parser("add", help="Set a reminder or timer.")
    adding.add_argument("request", help='e.g. "remind me to stretch in 10 minutes"')

    cancelling = commands.add_parser("cancel", help="Cancel one reminder.")
    cancelling.add_argument("id", type=int)

    clearing = commands.add_parser("clear", help="Cancel every reminder.")
    clearing.add_argument("-y", "--yes", action="store_true", help="Skip confirmation.")

    watching = commands.add_parser("watch", help="Announce reminders as they fall due.")
    watching.add_argument(
        "--once", action="store_true", help="Deliver what is due now, then exit."
    )
    return parser


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
