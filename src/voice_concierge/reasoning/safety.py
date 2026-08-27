"""Deterministic handling for requests that must not depend on model output."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SafetyIntervention:
    """A local response that takes precedence over generated content."""

    spoken_response: str
    guard: str


_GAS_EMERGENCY = re.compile(
    r"\b(?:(?:i|we)\s+(?:can\s+)?smell\s+gas|"
    r"(?:i(?:['’]m|\s+am)|we(?:['’]re|\s+are))\s+smelling\s+gas|"
    r"there(?:['’]s|\s+is)\s+(?:a\s+)?(?:gas\s+leak|gas\s+odou?r)|"
    r"(?:i|we)\s+(?:think|suspect)\s+(?:(?:there(?:['’]s|\s+is))|"
    r"(?:we\s+have))\s+(?:a\s+)?gas\s+leak|"
    r"(?:gas\s+leak|gas\s+odou?r)\s+(?:in|at)\s+(?:my|our|the)\s+"
    r"(?:house|home|building|kitchen|room))\b",
    flags=re.IGNORECASE,
)
_FIRE_EMERGENCY = re.compile(
    r"\b(?:(?:my|our|the)\s+(?:house|home|building|kitchen|room)\s+"
    r"(?:is\s+)?(?:on\s+fire|filling\s+with\s+smoke)|"
    r"there(?:['’]s|\s+is)\s+(?:a\s+)?fire|"
    r"(?:fire|smoke|smoke\s+and\s+fire|fire\s+and\s+smoke)\s+in\s+"
    r"(?:my|our|the)\s+(?:house|home|building|kitchen|room))\b",
    flags=re.IGNORECASE,
)
_MEDICAL_EMERGENCY = re.compile(
    r"\b(?:(?:i|they|he|she|someone)\s+(?:can(?:not|['’]t))\s+breathe|"
    r"(?:i|they|he|she|someone)\s+(?:have|has|am\s+having|is\s+having|"
    r"are\s+having)\s+(?:(?:severe|sudden|crushing|intense|bad)\s+)?"
    r"chest\s+pain|"
    r"(?:i(?:['’]m|\s+am)|they(?:['’]re|\s+are)|he(?:['’]s|\s+is)|"
    r"she(?:['’]s|\s+is)|someone\s+is)\s+bleeding\s+"
    r"(?:badly|heavily|severely)|"
    r"(?:i|they|he|she|someone)\s+(?:have|has|am\s+having|is\s+having|"
    r"are\s+having)\s+(?:signs?\s+of\s+)?a\s+stroke)\b",
    flags=re.IGNORECASE,
)
_FALL_EMERGENCY = re.compile(
    r"\b(?:i(?:['’]ve|\s+have)?|we(?:['’]ve|\s+have)?|"
    r"they(?:['’]ve|\s+have)?|he(?:['’]s|\s+has)?|"
    r"she(?:['’]s|\s+has)?|someone(?:['’]s|\s+has)?)\s+"
    r"(?:fallen|fell)\b[\s\S]{0,64}\b"
    r"(?:(?:can(?:not|['’]t))|unable\s+to)\s+"
    r"(?:get\s+(?:back\s+)?up|stand(?:\s+up)?|rise)\b",
    flags=re.IGNORECASE,
)
_CHEST_PAIN_DIAGNOSIS = re.compile(
    r"\b(?:diagnos(?:e|is|ing)|what(?:['’]s|\s+is)\s+wrong)\b"
    r"[\s\S]{0,64}\bchest\s+pain\b|"
    r"\bchest\s+pain\b[\s\S]{0,64}\b"
    r"(?:diagnos(?:e|is|ing)|what(?:['’]s|\s+is)\s+wrong)\b",
    flags=re.IGNORECASE,
)
_MEDICATION = re.compile(
    r"\b(?:medication|medicine|painkillers?|tablets?|pills?|capsules?)\b",
    flags=re.IGNORECASE,
)
_DOSE_QUESTION = re.compile(
    r"\b(?:how\s+(?:many|much)|what\s+(?:dose|dosage)|"
    r"(?:can|could|should|would)\s+(?:i|we|they)\s+take)\b",
    flags=re.IGNORECASE,
)
_DOSE_ACTION = re.compile(
    r"\b(?:take|use|extra|more|another|double|increase|dose|dosage)\b",
    flags=re.IGNORECASE,
)
_DRIVING_DISTRACTION = re.compile(
    r"\b(?:detailed|step[- ]by[- ]step|recipe)\b",
    flags=re.IGNORECASE,
)


def resolve_safety_intervention(
    transcript: str,
    *,
    mode: str = "home",
) -> SafetyIntervention | None:
    """Return a deterministic safety response for a recognized high-risk intent."""

    if _GAS_EMERGENCY.search(transcript):
        return SafetyIntervention(
            spoken_response=(
                "Leave the building immediately without using switches, plugs, or "
                "flames. From a safe place, call emergency services or your gas "
                "emergency service."
            ),
            guard="gas_emergency_safety",
        )

    if _FIRE_EMERGENCY.search(transcript):
        return SafetyIntervention(
            spoken_response=(
                "Leave the building immediately, stay outside, and call emergency "
                "services from a safe place."
            ),
            guard="fire_emergency_safety",
        )

    if _MEDICAL_EMERGENCY.search(transcript):
        return SafetyIntervention(
            spoken_response=(
                "Call emergency services now. If someone is nearby, ask them to "
                "help and follow the emergency dispatcher's instructions."
            ),
            guard="medical_emergency_safety",
        )

    if _FALL_EMERGENCY.search(transcript):
        return SafetyIntervention(
            spoken_response=(
                "Call emergency services or use an emergency alarm now. If you "
                "cannot reach either, call out for help and avoid moving if you may "
                "be injured."
            ),
            guard="fall_emergency_safety",
        )

    if _CHEST_PAIN_DIAGNOSIS.search(transcript):
        return SafetyIntervention(
            spoken_response=(
                "I cannot diagnose chest pain. If it is severe, new, or accompanied "
                "by breathing difficulty, call emergency services now; otherwise "
                "contact a healthcare professional promptly."
            ),
            guard="medical_diagnosis_safety",
        )

    if (
        _MEDICATION.search(transcript)
        and _DOSE_QUESTION.search(transcript)
        and _DOSE_ACTION.search(transcript)
    ):
        return SafetyIntervention(
            spoken_response=(
                "I cannot tell you how much extra medication to take. Contact a "
                "pharmacist or healthcare professional, and call emergency services "
                "if you may have taken too much or feel seriously unwell."
            ),
            guard="medication_dose_safety",
        )

    if mode == "driving" and _DRIVING_DISTRACTION.search(transcript):
        return SafetyIntervention(
            spoken_response=(
                "I won't provide detailed instructions while you're driving. Please "
                "park somewhere safe first."
            ),
            guard="driving_distraction_safety",
        )

    return None
