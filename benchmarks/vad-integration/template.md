# VAD Integration Benchmark — Silero VAD

## Device

- Date:
- Machine:
- Chip:
- OS:
- Python:
- Tool: Silero VAD
- Backend: PyTorch (CPU)

## Configuration

- THRESHOLD:
- MIN_SILENCE_BEFORE_UTTERANCE_END_MS:
- SPEECH_PAD_MS:
- CHUNK:

## Notes on measurements

- Utterance duration is measured from `"start"` VAD event to `"end"` VAD event.
  Excludes time before speech begins but is consistent across runs.
- RAM (python) is measured via tracemalloc — Python-level allocations only,
  excludes native libraries such as PyTorch and PyAudio.
- RAM (system/RSS) is measured via psutil RSS (Resident Set Size) — total memory
  the OS has allocated to the process, including native libraries.
- CPU is measured via psutil `cpu_percent()` — the value represents average CPU
  usage of the process since the warm-up call at the start of `capture_utterance`.

---

## Test 1 — Short utterance, quiet room

RAM (python) current: MB
RAM (python) peak: MB
RAM (system/RSS): MB
CPU at detection: %

| Attempt | Utterance | Captured | Duration (ms) | Samples |
|---------|-----------|----------|---------------|---------|
| 1       |           |          |               |         |
| 2       |           |          |               |         |
| 3       |           |          |               |         |
| 4       |           |          |               |         |
| 5       |           |          |               |         |

Capture rate:
Average duration (ms):
Average samples:

---

## Test 2 — Mid-utterance pause

RAM (python) current: MB
RAM (python) peak: MB
RAM (system/RSS): MB
CPU at detection: %

| Attempt | Utterance | Cut off early | Duration (ms) |
|---------|-----------|---------------|---------------|
| 1       |           |               |               |
| 2       |           |               |               |
| 3       |           |               |               |
| 4       |           |               |               |
| 5       |           |               |               |

Early cut-off rate:
Average duration (ms):

---

## Test 3 — Silence timeout

| Attempt | Behaviour observed | Duration before timeout (ms) |
|---------|--------------------|------------------------------|
| 1       |                    |                              |
| 2       |                    |                              |
| 3       |                    |                              |

---

## Test 4 — Background noise, short utterance

Background noise source:
RAM (python) current: MB
RAM (python) peak: MB
RAM (system/RSS): MB
CPU at detection: %

| Attempt | Utterance | Captured | Duration (ms) | Samples |
|---------|-----------|----------|---------------|---------|
| 1       |           |          |               |         |
| 2       |           |          |               |         |
| 3       |           |          |               |         |
| 4       |           |          |               |         |
| 5       |           |          |               |         |

Capture rate:
Average duration (ms):
Average samples:

---

## Issues observed

---

## Recommendation
