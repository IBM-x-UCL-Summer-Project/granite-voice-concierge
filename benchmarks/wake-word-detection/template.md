# Wake Word Detection Spike Results

## Device

- Date: Date
- Machine: Device
- Python: Version
- Model: Model
- Tool: openWakeWord (ONNX backend)

## Test 1 — Quiet room, live voice

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
