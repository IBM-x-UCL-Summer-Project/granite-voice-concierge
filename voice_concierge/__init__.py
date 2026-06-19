"""Repository-local import shim for the ``src`` package layout.

This lets commands run from the repository root import ``voice_concierge``
without requiring a manual ``PYTHONPATH=src`` prefix.
"""

from __future__ import annotations

from pathlib import Path

_SRC_PACKAGE = Path(__file__).resolve().parent.parent / "src" / "voice_concierge"

if _SRC_PACKAGE.is_dir():
    src_package = str(_SRC_PACKAGE)
    if src_package not in __path__:
        __path__.append(src_package)
