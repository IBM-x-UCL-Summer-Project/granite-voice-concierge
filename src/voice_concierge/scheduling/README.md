# scheduling

**Local reminders and timers.** Set them by voice or from the command line,
one-off or repeating. Everything is stored on the device and works with no
network.

## Design

A pure core with a thin surface, as elsewhere in the codebase.

- `parser.py` - turns a spoken request into a reminder. Rule-based, not a model
  call, and it **refuses rather than guesses** (see below).
- `recurrence.py` - pure arithmetic for "when does this fire next". Takes the
  current time as an argument, so a reminder missed while the machine was
  asleep is an ordinary test rather than something you can only see by waiting.
- `types.py` - `Reminder` and `Schedule`, stored as UTC epoch seconds and only
  turned into wall-clock time when read out to a person.
- `store.py` - SQLite under `.local/reminders/`, so a reminder outlives the
  process that set it.
- `service.py` - the rules between storage and announcing: what is due, what
  happens after delivery, what to say when one is set.
- `runner.py` - `check_once` delivers what is due (a plain call, fully tested);
  `ReminderRunner` calls it on a timer in the background.

## Three decisions worth knowing

**Refuse rather than guess.** "Remind me to buy milk" has no time in it, so
nothing is stored and the assistant asks. A reminder that arrives at the wrong
hour is worse than one that was never set, and unlike a model, a rule set can
decline. The same applies to "every Wednesday" with no time of day.

**A missed reminder is announced late, never skipped.** If the assistant was off
when one came due, it is delivered on the next start. A repeat missed for a week
fires **once** and moves to the next slot, rather than firing hundreds of times
to catch up.

**A failed announcement leaves the reminder due.** If speaking fails, the
reminder stays pending and is retried, so a broken speaker delays a reminder
instead of swallowing it. The app's `SpokenNotifier` prints as well as speaks,
so it only reports success once the user has been told somehow.

## Recurrence

Deliberately narrower than a calendar rule: `once`, `interval` (every N
minutes/hours), `daily` (at a time of day) and `weekly` (on a weekday, at a time
of day). These are the cases a spoken assistant is actually asked for, and each
can be described back clearly. Daily and weekly advance in **local wall-clock
time**, so "every morning at eight" does not drift by an hour across a
daylight-saving change.

## Usage

By voice, in the live app:

| Say | Result |
| --- | --- |
| "set a timer for ten minutes" | a one-off timer |
| "remind me to take my pills at 8pm" | a one-off reminder |
| "remind me to stretch every 20 minutes" | repeats on an interval |
| "remind me to call mum every day at 9" | repeats daily |
| "remind me to put the bin out every Tuesday at 7pm" | repeats weekly |
| "what reminders do I have" | reads back what is set |
| "cancel all reminders" | clears them |

From the command line:

```bash
python -m voice_concierge.scheduling                   # what is set
python -m voice_concierge.scheduling add "remind me to stretch in 10 minutes"
python -m voice_concierge.scheduling cancel 3
python -m voice_concierge.scheduling clear             # asks you to type CLEAR
python -m voice_concierge.scheduling watch             # announce as they fall due
python -m voice_concierge.scheduling watch --once      # deliver overdue, then exit
```

```python
from voice_concierge.scheduling import build_reminder_service

service = build_reminder_service()
reminder = service.create_from_speech("remind me to stretch in 10 minutes")
print(service.confirmation(reminder))
```

Reminders are on by default in the live app; `--no-reminders` turns them off.

## What is stored

One SQLite file at `.local/reminders/reminders.sqlite3`, holding the text, the
kind (reminder or timer), the due time, the repeat rule and whether it has been
delivered. Nothing else, and nothing leaves the device.
