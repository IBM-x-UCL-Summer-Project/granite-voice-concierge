# Wake Word Detection Spike Results

## Device

- Date: Date
- Machine: Device
- Chip: Chip
- OS: OS
- Python: Version
- Model: Model
- Tool: openWakeWord (ONNX backend)
- Threshold:

## Notes on measurements

- Latency is measured from the start of `oww_model.predict()` on the triggering
  chunk to callback. Excludes audio buffering time but is consistent across runs.
- RAM (python) is measured via tracemalloc — Python-level allocations only,
  excludes native libraries such as ONNX Runtime and PyAudio.
- RAM (system/RSS) is measured via psutil RSS (Resident Set Size) — total memory
  the OS has allocated to the process, including native libraries. More accurate
  than tracemalloc as a true measure of process memory cost.
- CPU is measured via psutil at the moment of detection — a snapshot rather than
  a sustained average during continuous listening.

## Test 1 — Quiet room, live voice

- RAM (python) current: X MB (avg across detections)
- RAM (python) peak: X MB (highest across all runs)
- RAM (system/RSS): X MB (avg across detections)
- CPU at detection: X% avg / X% peak

| Attempt | Detected | Confidence | Latency (ms) |
|---------|----------|------------|--------------|
| 1       |          |            |              |
| 2       |          |            |              |
| 3       |          |            |              |
| 4       |          |            |              |
| 5       |          |            |              |
| 6       |          |            |              |
| 7       |          |            |              |
| 8       |          |            |              |
| 9       |          |            |              |
| 10      |          |            |              |

Detection rate:
Average confidence:
Average latency (ms):

## Test 2 — Similar-sounding words (false positive check)

- RAM (python) current: X MB (avg across detections)
- RAM (python) peak: X MB (highest across all runs)
- RAM (system/RSS): X MB (avg across detections)
- CPU at detection: X% avg / X% peak

Word spoken - hey Harris

| Attempt | Detected | Confidence |
|---------|----------|------------|
| 1       |          |            |
| 2       |          |            |
| 3       |          |            |
| 4       |          |            |
| 5       |          |            |

False positive rate:

Word spoken - hey Travis

| Attempt | Detected | Confidence |
|---------|----------|------------|
| 1       |          |            |
| 2       |          |            |
| 3       |          |            |
| 4       |          |            |
| 5       |          |            |

False positive rate:

Word spoken - hey Marvis

| Attempt | Detected | Confidence |
|---------|----------|------------|
| 1       |          |            |
| 2       |          |            |
| 3       |          |            |
| 4       |          |            |
| 5       |          |            |

False positive rate:
Overrall false positive rate:

## Test 3 — Background noise, live voice

- RAM (python) current: X MB (avg across detections)
- RAM (python) peak: X MB (highest across all runs)
- RAM (system/RSS): X MB (avg across detections)
- CPU at detection: X% avg / X% peak

| Attempt | Detected | Confidence | Latency (ms) |
|---------|----------|------------|--------------|
| 1       |          |            |              |
| 2       |          |            |              |
| 3       |          |            |              |
| 4       |          |            |              |
| 5       |          |            |              |
| 6       |          |            |              |
| 7       |          |            |              |
| 8       |          |            |              |
| 9       |          |            |              |
| 10      |          |            |              |

Detection rate:
Average confidence:
Average latency (ms):

## Test 4 — Audio playback, quiet room (threshold: 0.3)

- Background noise source:
- RAM (python) current: X MB (avg across detections)
- RAM (python) peak: X MB (highest across all runs)
- RAM (system/RSS): X MB (avg across detections)
- CPU at detection: X% avg / X% peak

| Attempt | Source          | Detected | Confidence | Latency (ms) |
|---------|-----------------|----------|------------|--------------|
| 1       | hey_jarvis.wav  |          |            |              |
| 2       | hey_jarvis.wav  |          |            |              |
| 3       | hey_jarvis.wav  |          |            |              |
| 4       | hey_jarvis.wav  |          |            |              |
| 5       | hey_jarvis.wav  |          |            |              |

Detection rate:
Average confidence:
Average latency (ms):

## Threshold Comparison (quiet room, live voice)

Run Test 1 again at each threshold and record the summary figures here.

| Threshold | Detection rate | False positive rate | Avg confidence | Avg latency (ms) |
|-----------|----------------|---------------------|----------------|------------------|
| 0.3       |                |                     |                |                  |
| 0.5       |                |                     |                |                  |
| 0.7       |                |                     |                |                  |

## RAM / CPU

- Current RAM at detection: MB
- Peak RAM during session: MB
- CPU usage during continuous listening: %

## Issues observed

## Recommendation
