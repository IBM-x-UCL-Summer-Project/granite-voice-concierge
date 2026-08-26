# Local Reasoning Evaluation

The final comparison is a requirements-based benchmark for the reasoning layer
used by the voice concierge. It is not a general-purpose measure of model
intelligence.

## Final comparison

`prompts/final-v1.json` is the frozen 30-case suite. It contains:

- 6 general independent-living requests;
- 5 missing-context requests;
- 5 safety-sensitive requests;
- 5 requests requiring current external information while offline;
- 5 memory and confirmation requests; and
- 4 structured-output and response-length requests.

Comparison mode defaults to three repetitions of every case and one unmeasured
warm-up request per model. Seven models therefore produce 630 measured responses:

```bash
python -m benchmarks.reasoning.benchmark compare \
  --models \
    qwen3:8b \
    granite4.1:8b \
    llama3.1:8b \
    phi4-mini:3.8b \
    gemma3:4b \
    mistral:7b \
    granite3.3:2b
```

The default generation configuration is prompt version `v3`, temperature `0.2`,
top-p `0.9`, a 4096-token context, structured JSON output, and a 60-word spoken
response constraint. Model-specific thinking is explicitly disabled in comparison
mode so every model uses the same measured response path. The current token-budget
calculation sends `num_predict=304` for an ordinary single-model run. The final
comparison fixes `num_predict=512` so the surrounding JSON fields do not compete
with the 60-word spoken response for the smaller derived budget. No sampling seed
is set. The detailed reports record the effective values returned by the runtime.

## Scoring

The Python harness scores every response automatically; no human or LLM judge is
used. A response passes only if all applicable checks pass, with no partial
credit. The global check enforces the spoken word limit. Individual cases can
also check confirmation state, memory action, information source, freshness,
required terms, and forbidden terms.

Raw and guarded evaluations come from one inference:

- **Raw** is the schema-parsed response before deterministic policy guards and
  word-limit shaping.
- **Guarded** is the same response after those application controls.
- **Guard interventions** counts responses carrying a named `policy_guard`. An
  intervention does not necessarily mean that a failing response became a pass,
  and word-limit truncation alone is not counted.

Latency covers local generation, schema parsing, policy guards, and word-limit
shaping. Automated scoring and the explicit warm-up request are excluded.

## Evidence

Each comparison creates a timestamped directory under `results/` containing one
JSON report per model plus JSON and Markdown summaries. Reports include the suite
SHA-256, settings, hardware, software revision, model digest, parameter size,
quantisation, warm-up latency, every response, every check result, and every
guard intervention.
