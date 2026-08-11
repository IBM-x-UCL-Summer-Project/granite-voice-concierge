"""Entry point so reminders run as `python -m voice_concierge.scheduling`."""

# Standard library
import sys

# Local
from voice_concierge.scheduling.cli import main

if __name__ == "__main__":  # pragma: no cover - process entry point
    sys.exit(main())
