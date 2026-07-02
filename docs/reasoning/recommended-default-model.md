# Recommended Default Reasoning Model

## Decision

Use `granite4.1:8b` as the recommended default local reasoning model for the
current prototype.

Keep `granite3.3:2b` as the lower-resource fallback. The selected model should
remain configurable so users can later choose another compatible local model.

## Why 8B Is Recommended

The latest local comparison covered 13 voice-concierge reasoning cases across
cooking, shopping, memory, accessibility, safety, and offline behavior.

| Model           | Raw pass | Guarded pass | Guard interventions | Average latency |
| --------------- | -------: | -----------: | ------------------: | --------------: |
| `granite4.1:8b` |   69.23% |       92.31% |                   7 |      2,037.8 ms |
| `granite3.3:2b` |   69.23% |       92.31% |                   7 |        851.7 ms |

The automated scores are tied, but the 8B model handled the missing context
cooking case correctly, while the 2B model claimed to repeat a step that had not
been supplied. Avoiding invented context is important for a predictable assistant
supporting independent living.

The 8B model is therefore the preferred quality oriented starting point. Its
observed latency remains plausible for the prototype, while the 2B model provides
a materially faster option for constrained hardware.

## Limits of This Decision

This is a practical default selection, not proof that 8B is universally better.
The suite is small, each case was run once, and deterministic policy guards
changed 7 of 13 responses. The results do not yet measure the complete voice
pipeline, repeated run latency, memory use, or behavior on target devices.

## Model Switching

Final version of the product should allow a user to pick models based on preferences.

Evidence source: local comparison run
`benchmarks/reasoning/results/model-comparison-20260617-221036/` from 17 June 2026.
