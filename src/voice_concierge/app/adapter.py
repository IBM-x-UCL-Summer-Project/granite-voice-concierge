"""Framework-free backend adapter for one app pipeline turn."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from voice_concierge.app.pipeline import VoiceConciergePipeline
from voice_concierge.app.serialization import (
    JsonDict,
    app_turn_request_from_dict,
    app_turn_result_to_dict,
)


def handle_turn(
    payload: Mapping[str, Any],
    pipeline: VoiceConciergePipeline,
) -> JsonDict:
    """Process one serialized transcript turn through the app pipeline."""

    request = app_turn_request_from_dict(payload)
    result = pipeline.process_request(request)
    return app_turn_result_to_dict(result)
