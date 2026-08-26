# Local Reasoning Evaluation

This directory contains the single canonical evaluation for the voice
concierge's local reasoning layer. It is a requirements-based product benchmark,
not a general measure of model intelligence.

## Canonical suite

[`prompts/final-v1.json`](prompts/final-v1.json) is the only benchmark suite used
for the final report. Its SHA-256 is
`e5c26cd6c7a6c820700f5b8e48b5dec4fef77fb9fb8e9751df4d02c023cc089c`.
The 30 fixed cases comprise:

- 6 general independent-living requests;
- 5 missing-context requests;
- 5 safety-sensitive requests;
- 5 current-information requests made under offline constraints;
- 5 memory and confirmation requests; and
- 4 structured-output and response-length requests.

Each case is executed three times per model. Seven models therefore produce 90
responses per model and 630 measured responses overall. One warm-up request per
model is excluded from scoring and reported latency.

## Run the final comparison

Run every command from the repository root.

1. Create an environment and install the project dependencies:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   python -m pip install -r requirements-dev.txt
   ```

2. Start Ollama locally, then install the seven exact model tags:

   ```bash
   ollama pull qwen3:8b
   ollama pull granite4.1:8b
   ollama pull llama3.1:8b
   ollama pull phi4-mini:3.8b
   ollama pull gemma3:4b
   ollama pull mistral:7b
   ollama pull granite3.3:2b
   ollama list
   ```

3. Run the comparison:

   ```bash
   python -m benchmarks.reasoning.benchmark compare \
     --host http://localhost:11434 \
     --models \
       qwen3:8b \
       granite4.1:8b \
       llama3.1:8b \
       phi4-mini:3.8b \
       gemma3:4b \
       mistral:7b \
       granite3.3:2b
   ```

No additional flags are required to reproduce the final method. Comparison mode
defaults to the canonical suite, three repetitions, one excluded warm-up,
raw-and-guarded evaluation, and the generation settings below. The command exits
non-zero only when every model fails to run; inspect the summary's `error` field
to confirm that every candidate succeeded.

Each run creates a timestamped directory under `results/` containing seven model
JSON files, `comparison-summary.json`, and `comparison-summary.md`. These generated
artifacts are intentionally git-ignored. A complete run must contain seven
successful models and 630 responses in total.

For a quick plumbing check that does not require Ollama, run:

```bash
python -m benchmarks.reasoning.benchmark run --engine fake
```

## Fixed generation settings

The comparison uses the same local Ollama request path and settings for every
model:

| Setting | Value |
| --- | --- |
| Runtime prompt | `v3` (`local-reasoning`) |
| Policy profile | `strict` |
| Output format | Schema-constrained JSON |
| Temperature | `0.2` |
| Top-p | `0.9` |
| Context window | `4096` tokens |
| Prediction budget | `512` tokens |
| Spoken response limit | `60` words |
| Model thinking | Explicitly disabled |
| Sampling seed | Not set |
| Keep-alive | `5m` |
| Request timeout | `180` seconds |

The fixed 512-token comparison budget leaves enough space for the full structured
response. Ordinary single-model application requests continue to derive a
smaller budget from the requested spoken-word limit; with the default 60-word
limit that derived value is 304 tokens.

## Scoring definitions

Scoring is performed automatically by the deterministic Python harness. No human
or LLM judge is used, and there is no partial credit. A response passes only when
all applicable checks pass.

The two global checks require a schema-valid structured response and a spoken
response of at most 60 words. Case-specific checks can require the expected:

- confirmation state;
- memory action (`store`, `update`, `delete`, or no action);
- information source and freshness classification;
- required term or set of terms; and
- absence of forbidden terms.

A generation that cannot be validated against the structured-response schema is
recorded as a schema failure and fails both evaluation stages.

- **Raw pass** evaluates the schema-parsed model response before deterministic
  policy guards and word-limit shaping. It is not the untouched Ollama text.
- **Guarded pass** evaluates the same generation after application policy guards
  and word-limit shaping.
- **Guard interventions** counts generations whose guarded metadata contains a
  named `policy_guard`. It does not count word-limit truncation alone and does not
  imply that a raw failure became a guarded pass.

Latency is wall-clock time for local generation, schema parsing, deterministic
policy guards, and word-limit shaping. It excludes the explicit warm-up,
automated scoring, speech recognition, and text-to-speech synthesis.

## Definitive local run

The report values below come from the complete run on 26 August 2026 at Git
revision `329650778fee1210d9de6146f7cef6ed033e96ad`. The machine was an Apple
arm64 Mac running macOS 15.7 with 24 GiB system memory. All seven models used
`Q4_K_M` quantisation. The software environment was Python 3.12.6, Ollama
0.32.14, and Ollama Python client 0.6.2.

| Model | Parameters | Raw pass | Guarded pass | Guard interventions | Schema failures | Avg. latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `qwen3:8b` | 8.2B | 72/90 (80.00%) | 69/90 (76.67%) | 54 | 6 | 2,268.4 ms |
| `granite4.1:8b` | 8.8B | 68/90 (75.56%) | 67/90 (74.44%) | 42 | 3 | 2,556.9 ms |
| `llama3.1:8b` | 8.0B | 60/90 (66.67%) | 67/90 (74.44%) | 47 | 4 | 2,710.1 ms |
| `phi4-mini:3.8b` | 3.8B | 44/90 (48.89%) | 52/90 (57.78%) | 40 | 10 | 1,349.9 ms |
| `gemma3:4b` | 4.3B | 45/90 (50.00%) | 54/90 (60.00%) | 36 | 15 | 1,871.4 ms |
| `mistral:7b` | 7.2B | 62/90 (68.89%) | 66/90 (73.33%) | 47 | 13 | 2,597.7 ms |
| `granite3.3:2b` | 2.5B | 45/90 (50.00%) | 45/90 (50.00%) | 60 | 20 | 1,118.8 ms |

Exact Ollama digests:

```text
qwen3:8b          500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41
granite4.1:8b     444af1c4b2fedd6b54041aca558e7300b0b3d5c0468c44619126240323ba2852
llama3.1:8b       46e0c10c039e019119339687c3c1757cc81b9da49709a3b3924863ba87ca666e
phi4-mini:3.8b    78fad5d182a7c33065e153a5f8ba210754207ba9d91973f57dffa7f487363753
gemma3:4b         a2af6cc3eb7fa8be8504abaf9b04e88f17a119ec3f04a3addf55f92841195f5a
mistral:7b        6577803aa9a036369e481d648a2baebb381ebc6e897f2bb9a766a2aa7bfbc1cf
granite3.3:2b     07bd1f170855240f9e162bf54ea494a8bc1c73d8cbd1365d7fccbeb7d2504947
```

The automated checks are requirements diagnostics, not a general quality score.
Guarded scores may be lower than raw scores when a safety guard replaces an
otherwise check-passing answer with text that fails a case-specific lexical
check. Detailed responses should therefore be reviewed before making a model
selection decision.
