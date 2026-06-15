# Python Style Guide

This is just a basic guide so our Python code stays reasonably consistent.

## Naming

Use:

```text
snake_case for functions and variables
PascalCase for classes
UPPER_CASE for constants
```

## Formatting tools

I am using **Black** for formatting and **Ruff** for basic linting/import checks.

The shared settings are stored in:

```text
pyproject.toml
```

This should help keep formatting consistent across the project, as long as the tools are using the repo config.

## VS Code setup

I am using VS Code, so I have added:

```text
.vscode/settings.json
```

This sets Python files to format on save using the Black Formatter extension.

Recommended VS Code extensions:

```text
Python
Black Formatter
Ruff
```

The full repo folder should be opened in VS Code, not just `src/` or another subfolder, otherwise VS Code may not find the `pyproject.toml` config.

## Installing tools manually

If VS Code formatting/linting does not work, or if someone wants to run the tools from the terminal, the dev tools can be installed with:

```bash
python -m pip install -r requirements-dev.txt
```

Then run:

```bash
python -m black .
python -m ruff check .
python -m pytest
```

## Editor settings

The repo does not currently include an `.editorconfig` file.

If anyone wants editor neutral settings, an `.editorconfig` file can be added using the same basic settings from `.vscode/settings.json`.

## Type hints

Use type hints for new code where they make things clearer, especially for component interfaces.

Example:

```python
def retrieve_memories(query: str, limit: int = 5) -> list[str]:
    ...
```

## Imports

Keep imports organised roughly like this:

```python
# Standard library
from pathlib import Path

# Third-party
import numpy as np

# Local
from voice_concierge.memory import MemoryStore
```

Avoid wildcard imports like:

```python
from module import *
```

## Comments

Use comments only when they help explain something non-obvious.

Prefer explaining why something is done, not repeating what the code already says.

## Tests

Use `pytest`.

Test files should be named like:

```text
test_memory_store.py
test_context_manager.py
test_granite_client.py
```

Code in `experiments/` can be rough. Code moved into `src/` should be cleaner and tested where practical.

## Do not commit

- API keys or tokens;
- `.env` files;
- large model files;
- generated audio files unless agreed;
- local system specific files.
