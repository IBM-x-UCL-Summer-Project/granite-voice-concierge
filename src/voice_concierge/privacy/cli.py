"""Command-line memory and privacy centre.

The user-facing surface over PrivacyCentre: it renders, prompts and confirms,
and holds no policy of its own. Keeping the two apart means a voice or web
front end can be added later without reimplementing any of the rules about what
may be changed or removed.

Destructive actions ask for confirmation, and erasing everything asks the user
to type the word rather than accept a keypress, because "forget everything" is
not recoverable and a misheard or mistyped yes should not be enough.

    python -m voice_concierge.privacy            # what is stored
    python -m voice_concierge.privacy list       # review memories
    python -m voice_concierge.privacy export     # take a copy as JSON
    python -m voice_concierge.privacy delete 12  # remove one
    python -m voice_concierge.privacy forget-all # remove everything
"""

# Standard library
import argparse
import json
import sys
from collections.abc import Callable, Sequence
from typing import TextIO

# Local
from voice_concierge.privacy.centre import PrivacyCentre
from voice_concierge.privacy.disclosure import build_report, format_report
from voice_concierge.privacy.errors import PrivacyError
from voice_concierge.privacy.factory import build_privacy_centre
from voice_concierge.privacy.types import StoredMemory

CONFIRM_WORD = "DELETE"  # typed in full before everything is erased


def format_memory(memory: StoredMemory, *, verbose: bool = False) -> str:
    """Render one memory for review."""
    head = f"[{memory.identifier}] {memory.content}"
    if not verbose:
        return head
    details = [
        f"    stored {memory.created_display}",
        f"    {memory.layer_description}",
    ]
    if memory.topic:
        details.append(f"    topic: {memory.topic}")
    if memory.source_type:
        details.append(f"    learned from: {memory.source_type}")
    return "\n".join([head, *details])


def show_storage(centre: PrivacyCentre, *, stdout: TextIO) -> int:
    """Explain what is stored on this device, and what is not."""
    report = build_report(centre)
    print(format_report(report), file=stdout)
    return 0


def show_list(
    centre: PrivacyCentre,
    *,
    layer: str | None,
    search: str | None,
    verbose: bool,
    stdout: TextIO,
) -> int:
    """List stored memories, newest first."""
    memories = centre.list_memories(layer=layer, search=search)
    if not memories:
        print("Nothing is stored that matches.", file=stdout)
        return 0
    for memory in memories:
        print(format_memory(memory, verbose=verbose), file=stdout)
    print(f"\n{len(memories)} memories.", file=stdout)
    return 0


def show_export(centre: PrivacyCentre, *, stdout: TextIO) -> int:
    """Print every stored memory as JSON, so the user can keep a copy."""
    print(json.dumps(centre.export_memories(), indent=2), file=stdout)
    return 0


def run_edit(
    centre: PrivacyCentre, identifier: int, content: str, *, stdout: TextIO
) -> int:
    """Correct the content of one memory."""
    updated = centre.edit_memory(identifier, content)
    print(f"Updated: {format_memory(updated)}", file=stdout)
    return 0


def run_delete(
    centre: PrivacyCentre,
    identifier: int,
    *,
    assume_yes: bool,
    confirm: Callable[[str], str],
    stdout: TextIO,
) -> int:
    """Remove one memory, after showing the user exactly what will go."""
    memory = centre.get_memory(identifier)
    if memory is None:
        print(f"No memory with id {identifier} is stored.", file=stdout)
        return 1
    print(format_memory(memory), file=stdout)
    if not assume_yes and confirm("Delete this memory? [y/N] ").strip().lower() not in (
        "y",
        "yes",
    ):
        print("Left unchanged.", file=stdout)
        return 0
    centre.delete_memory(identifier)
    print("Deleted.", file=stdout)
    return 0


def run_forget_all(
    centre: PrivacyCentre,
    *,
    assume_yes: bool,
    confirm: Callable[[str], str],
    stdout: TextIO,
) -> int:
    """Erase every stored memory, after an explicit typed confirmation."""
    total = len(centre.list_memories())
    if total == 0:
        print("Nothing is stored, so there is nothing to erase.", file=stdout)
        return 0
    if not assume_yes:
        print(
            f"This permanently erases all {total} stored memories and their "
            "search index. It cannot be undone.",
            file=stdout,
        )
        if confirm(f"Type {CONFIRM_WORD} to confirm: ").strip() != CONFIRM_WORD:
            print("Left unchanged.", file=stdout)
            return 0
    removed = centre.delete_all()
    print(f"Erased {removed} memories.", file=stdout)
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    centre: PrivacyCentre | None = None,
    confirm: Callable[[str], str] = input,
    stdout: TextIO = sys.stdout,
) -> int:
    """Run the privacy centre from the command line."""
    args = _build_parser().parse_args(argv)
    active = centre if centre is not None else build_privacy_centre()
    try:
        return _dispatch(args, active, confirm=confirm, stdout=stdout)
    except PrivacyError as exc:
        # Report and fail loudly: a privacy action that did not happen must
        # never look like one that did.
        print(f"Could not complete that: {exc}", file=stdout)
        return 1


def _dispatch(
    args: argparse.Namespace,
    centre: PrivacyCentre,
    *,
    confirm: Callable[[str], str],
    stdout: TextIO,
) -> int:
    """Route a parsed command to its handler."""
    if args.command == "list":
        return show_list(
            centre,
            layer=args.layer,
            search=args.search,
            verbose=args.verbose,
            stdout=stdout,
        )
    if args.command == "export":
        return show_export(centre, stdout=stdout)
    if args.command == "edit":
        return run_edit(centre, args.id, args.content, stdout=stdout)
    if args.command == "delete":
        return run_delete(
            centre, args.id, assume_yes=args.yes, confirm=confirm, stdout=stdout
        )
    if args.command == "forget-all":
        return run_forget_all(
            centre, assume_yes=args.yes, confirm=confirm, stdout=stdout
        )
    return show_storage(centre, stdout=stdout)  # no command: explain what is stored


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m voice_concierge.privacy",
        description="Review, correct and remove what this assistant stores locally.",
    )
    commands = parser.add_subparsers(dest="command")

    listing = commands.add_parser("list", help="Review stored memories.")
    listing.add_argument("--layer", default=None, help="Only this memory layer.")
    listing.add_argument(
        "--search", default=None, help="Only memories containing this."
    )
    listing.add_argument(
        "-v", "--verbose", action="store_true", help="Show dates and sources."
    )

    commands.add_parser("export", help="Print all stored memories as JSON.")

    editing = commands.add_parser("edit", help="Correct a memory's content.")
    editing.add_argument("id", type=int)
    editing.add_argument("content")

    deleting = commands.add_parser("delete", help="Remove one memory.")
    deleting.add_argument("id", type=int)
    deleting.add_argument("-y", "--yes", action="store_true", help="Skip confirmation.")

    forgetting = commands.add_parser("forget-all", help="Erase every stored memory.")
    forgetting.add_argument(
        "-y", "--yes", action="store_true", help="Skip confirmation."
    )
    return parser


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
