# Development Workflow Guide

This document explains how the team should use GitHub to organise, track, review, and merge project work.

## 1. Project Board

The GitHub Project board is used to track the status of project tasks.

Current columns:

```text
Backlog → Ready → In Progress → In Review → Done
```

### Column meanings

| Column      | Meaning                                                                  |
| ----------- | ------------------------------------------------------------------------ |
| Backlog     | Work that may need to be done later                                      |
| Ready       | Work that is clearly defined and can be started                          |
| In Progress | Someone is actively working on the task                                  |
| In Review   | The work is complete and needs checking, testing, or pull request review |
| Done        | The task has been completed and accepted                                 |

The board should be treated as the main place to check current project progress.

## 2. Issues

GitHub Issues should be used for project tasks.

Each meaningful task should have an issue before work starts. This makes it clear:

- what needs to be done;
- who is responsible;
- what component it belongs to;
- what counts as complete.

Use the issue templates where possible (present in .github/).

## 3. Labels

Labels are used to organise issues by component, type of work, and priority.

The project uses three main label categories:

```text
component:<area>
type:<kind-of-work>
priority:<level>
```

The full list of available labels can be found in:

```text
Repository → Issues → Labels
```

Each issue should have at least one relevant component label and one type label. Priority labels can be added where useful.

## 4. Technical Spikes

A technical spike is a short investigation or prototype used to answer a technical question.

A spike is complete when it produces:

- a short working prototype or test, where applicable;
- setup notes;
- results or observations;
- a recommendation for what to do next.

Spike code should usually go in the `experiments/` folder.

## 5. Branches

The `main` branch is protected and should contain stable shared work.

New work should be done on a separate branch. Once the work is complete, it is merged back into `main` through a pull request.

Naming convention:

Work-type-based branches
`<type>/<short-description>`

Examples:

- spike/granite-local-inference
- feature/sqlite-memory-store
- docs/update-workflow-guide
- fix/stt-audio-path-error

This option groups branches by the kind of work being done.

Branch names should be short, lowercase, and use hyphens instead of spaces.

## 6. Pull Requests

A pull request should be opened when work is ready to be reviewed or merged.

Each pull request should explain:

- what changed;
- which issue it relates to;
- how it was tested;
- any known limitations or follow-up work.

Where possible, link the related issue using:

```text
Closes #issue-number
```

This automatically closes the issue when the pull request is merged.

## 7. Code and Document Review

At least one other team member should review meaningful changes before they are merged.

The reviewer should check:

- whether the change matches the issue;
- whether the code or document is understandable;
- whether setup or usage instructions are clear;
- whether there are obvious errors;
- whether any benchmark or test results are included where relevant.

## 8. Definition of Done

A task should only be moved to `Done` when:

- the agreed work has been completed;
- relevant code, notes, or documents have been committed;
- any related pull request has been reviewed and merged;
- setup or usage instructions are included where needed;
- the outcome is clear to the rest of the team.

For technical spikes, `Done` means the question has been answered and a recommendation has been recorded.

## 9. Team Working Rules

- Every active task should be visible on the project board.
- Every active task should have an owner.
- Large tasks should be split into smaller issues.
- Experimental work should be documented, even if the result is negative.
- Important technical choices should be supported by evidence from testing, research, or both.
- We should integrate work frequently rather than leaving all integration until the end.
