"""Named reasoning-policy profiles shared by prompts and local guards."""

from __future__ import annotations

from typing import Literal, cast

ReasoningPolicyProfile = Literal["strict", "uat_relaxed"]

STRICT_REASONING_POLICY_PROFILE: ReasoningPolicyProfile = "strict"
UAT_REASONING_POLICY_PROFILE: ReasoningPolicyProfile = "uat_relaxed"
SUPPORTED_REASONING_POLICY_PROFILES = frozenset(
    {STRICT_REASONING_POLICY_PROFILE, UAT_REASONING_POLICY_PROFILE}
)


def validate_reasoning_policy_profile(value: object) -> ReasoningPolicyProfile:
    """Return a supported profile or reject an ambiguous runtime value."""

    if not isinstance(value, str) or value not in SUPPORTED_REASONING_POLICY_PROFILES:
        choices = ", ".join(sorted(SUPPORTED_REASONING_POLICY_PROFILES))
        raise ValueError(f"Reasoning policy profile must be one of: {choices}.")
    return cast(ReasoningPolicyProfile, value)
