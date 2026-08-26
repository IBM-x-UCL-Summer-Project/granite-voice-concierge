# Recommended Default Reasoning Model

## Decision

Use `granite4.1:8b` as the default local reasoning model. Retain
`granite3.3:2b` as an explicitly configured, lower-resource startup fallback.
The fallback is used only when the primary model is absent at application
startup; it is not a mid-turn retry and is not downloaded automatically.

## Evidence and rationale

The definitive local comparison used 30 cases, three repetitions per case, and
90 responses per model. Under identical generation and scoring settings:

| Model | Raw pass | Guarded pass | Guard interventions | Schema failures | Average latency |
| --- | ---: | ---: | ---: | ---: | ---: |
| `granite4.1:8b` | 68/90 (75.56%) | 67/90 (74.44%) | 42 | 3 | 2,556.9 ms |
| `granite3.3:2b` | 45/90 (50.00%) | 45/90 (50.00%) | 60 | 20 | 1,118.8 ms |

The 8B Granite model was substantially more reliable and produced far fewer
schema-invalid responses, while the 2B model was approximately 1.4 seconds
faster per reasoning request on the measured machine. This supports using the
2B model only as a resource-constrained fallback rather than treating it as
quality-equivalent to the primary.

The seven-model comparison did not establish Granite 4.1 8B as the universal
best model. Qwen3 8B achieved the highest guarded pass count at 69/90, compared
with Granite's 67/90. Granite remains the project default because an IBM Granite
reasoning model is a client requirement and Granite 4.1 8B was competitive within
the evaluated model class. The backend remains configurable so another compatible
local model can be selected for deployments with different priorities.

The canonical [Local Reasoning Evaluation](../../benchmarks/reasoning/README.md)
contains the complete seven-model results, exact digests and quantisation,
generation settings, scoring definitions, reproduction command, and limitations.
That document is the source of truth for benchmark numbers.
