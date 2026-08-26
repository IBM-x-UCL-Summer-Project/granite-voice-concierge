# Voice pipeline benchmark suite

One command measures every component and the whole pipeline, and writes a dated
JSON record plus a Markdown report.

```bash
python -m benchmarks.suite --tts piper
```

Everything runs from synthesized and recorded audio, so no microphone and no
person are needed. A run takes roughly 5–15 minutes depending on the machine
and whether the reasoning model is loaded.

## Before you run it

You need the project environment and a local Ollama with the models pulled.
Check both without measuring anything:

```bash
python -m benchmarks.suite --preflight-only
```

That reports the same readiness checks the app uses, then probes the
text-to-speech backends and stops. Fix anything it marks `FAIL` before doing a
real run; `WARN` is usually fine.

If Piper has not been used on this machine before, prefetch the speech models
so the first measured run is not dominated by downloads:

```bash
python -c "from faster_whisper import WhisperModel; WhisperModel('base.en', device='cpu', compute_type='int8')"
```

```bash
python -c "from silero_vad import load_silero_vad; load_silero_vad()"
```

## Choosing the voice, and why it matters

The application composes Piper with the macOS voice behind a fallback chain, so
a user never loses speech when one backend fails. That is correct for the
product and wrong for a benchmark: if Piper fails, macOS audio is produced
silently and the numbers get published as Piper's. That is exactly what
happened to an earlier whole-pipeline run, which was labelled Piper and had in
fact measured `say`.

So this suite pins one backend and **refuses to substitute another**:

| Flag | Behaviour |
| --- | --- |
| `--tts piper` | Measures Piper. Aborts with a diagnosis if Piper cannot synthesize. **Default.** |
| `--tts say` | Measures the macOS voice. macOS only. |
| `--tts auto` | Uses the first backend that works, and names it in the report. |

The chosen backend appears in the report header, in the results filename, and
next to every figure it affected. Nothing in the application's own fallback
behaviour is changed by any of this.

If `--tts piper` aborts, the error names the cause and the fix. The failure
seen on one of our machines is a packaging defect in the `piper-tts` wheel,
which resolves its espeak-ng data through a path baked in at build time:

```
Error processing file '/Users/runner/work/piper1-gpl/.../espeak-ng-data/phontab':
No such file or directory
```

Reinstalling `piper-tts` usually clears it. If it does not, run with `--tts say`
and say so in whatever you write up — do not quote the result as Piper's.

## What gets measured

| Stage | Measures | Needs |
| --- | --- | --- |
| `tts` | Synthesis latency and real-time factor at three utterance lengths | Chosen backend |
| `stt` | Word error rate and transcription latency over 27 utterances | faster-whisper |
| `wake_word` | Detection, confusable and neutral activation across 3 thresholds × 4 noise levels | openWakeWord |
| `vad` | Utterance capture, plus the pause length at which speech gets cut off | Silero VAD |
| `reasoning` | Response latency for the local model | Ollama running |
| `pipeline` | End-to-end turn latency, memory, CPU and WER | Ollama running |

Run a subset with `--only` or `--skip`:

```bash
python -m benchmarks.suite --tts piper --only tts stt vad
```

```bash
python -m benchmarks.suite --tts piper --skip reasoning pipeline
```

A stage that cannot run is skipped, named in the report under "Stages that did
not run", and does not stop the others. A machine with no Ollama still produces
every speech result. The one thing that aborts the whole run is a pinned
text-to-speech backend that cannot synthesize.

## Useful options

| Flag | Purpose |
| --- | --- |
| `--turns N` | Whole-pipeline turns to record. Default 8. |
| `--stt-model small.en` | Try a larger speech-to-text model. |
| `--reasoning-model granite3.3:2b` | Measure the smaller model instead. |
| `--no-memory` | Run pipeline turns without the memory subsystem. |
| `--tag piper-rerun` | Label the output files. |
| `--output-dir path/` | Write results elsewhere. Default `benchmarks/suite/results/`. |

## Reading the output

Two files land in `benchmarks/suite/results/`, named by timestamp and backend:

- `20260825-084451-piper.md` — the report to read and quote from
- `20260825-084451-piper.json` — the full record, including every individual trial

**Commit both.** The reason this suite exists is that a published table could
not be traced to any saved run. Each report carries the git commit, the working
tree's dirty flag, the machine, and every relevant package version, so a figure
can always be tied back to what produced it.

## Limitations you must carry into any write-up

These are properties of the method, not bugs, and a report that omits them
overstates what was measured.

- **Audio is synthesized, not spoken.** Clean, evenly paced, single voice, no
  disfluency. Accuracy figures are ceilings. They say nothing about older-adult
  speech, which is the target group.
- **Replayed audio never passes through a speaker, a room or a microphone.**
  This matters most for the wake word. On clean replay the detector scores near
  0.9 on everything and the threshold sweep goes flat; live over-the-air trials
  in June saw confidences from 0.32 to 0.99, and a confusable phrase firing 5
  times out of 5 that clean replay rejects outright. The noise conditions exist
  to restore a usable gradient, but white noise is not a room. **Live trials
  remain the authority for any quoted detection rate.**
- **Wake-word latency is per-frame model inference.** It excludes audio
  capture, the 80 ms frame period, and the roughly 1.4 s of rolling context the
  model accumulates before it can decide. It is not user-perceived activation
  latency, which this suite does not measure.
- **The whole-pipeline span excludes wake word and VAD** (they need a live
  microphone) and excludes playback (its duration is a property of response
  length, not of system cost).
- **Sample sizes are small.** Eight turns cycling three requests is indicative,
  not a statistically powered sample. Repeat runs before treating any
  difference as real.

## Extending it

Test material lives in `corpus.py`. Adding utterances is the most useful change
you can make, but a run with an edited corpus is not comparable with an earlier
one — note it in the report when you do.

The modules split by responsibility: `harness.py` holds measurement plumbing
shared by every stage, `backends.py` handles backend pinning, `components.py`
has one function per stage, `pipeline.py` the end-to-end turn, and `report.py`
the rendering.
