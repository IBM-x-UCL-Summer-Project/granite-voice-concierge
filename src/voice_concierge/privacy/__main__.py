"""Entry point so the privacy centre runs as `python -m voice_concierge.privacy`."""

# Standard library
import sys

# Local
from voice_concierge.privacy.cli import main

if __name__ == "__main__":  # pragma: no cover - process entry point
    sys.exit(main())
