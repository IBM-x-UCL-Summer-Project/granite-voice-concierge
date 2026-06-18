# Wake Word Detection Spike Results

## Device

- Date: 18-06-2026
- Machine: MacBook Pro (14-inch, 2021)
- Chip: Apple M1 Pro
- OS: macOS 26.2
- Python: 3.9
- Model: hey_jarvis_v0.1.onnx
- Tool: openWakeWord (ONNX backend)
- Threshold: 0.3

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

RAM (python) current: 2.7 MB avg
RAM (python) peak: 4.8 MB
RAM (system/RSS): 91.1 MB avg
CPU during listening: 8.3% avg / 9.1% peak

| Attempt | Detected | Confidence | Latency (ms) |
|---------|----------|------------|--------------|
| 1       | Yes      | 0.85       | 8.2          |
| 2       | No       |            |              |
| 3       | No       |            |              |
| 4       | Yes      | 0.36       | 9.6          |
| 5       | Yes      | 0.54       | 10.3         |
| 6       | Yes      | 0.42       | 6.2          |
| 7       | Yes      | 0.99       | 10.6         |
| 8       | Yes      | 0.32       | 12.8         |
| 9       | Yes      | 0.54       | 5.9          |
| 10      | Yes      | 0.37       | 11.6         |

Detection rate: 80%
Average confidence: 0.55
Average latency (ms): 9.4

## Test 2 — Similar-sounding words (false positive check)

RAM (python) current: 3.0 MB avg
RAM (python) peak: 4.8 MB
RAM (system/RSS): 90.6 MB avg
CPU at detection: 7.6% avg / 8.3% peak

Word spoken - hey Harris

| Attempt | Detected | Confidence |
|---------|----------|------------|
| 1       | No       |            |
| 2       | Yes      | 0.47       |
| 3       | No       |            |
| 4       | No       |            |
| 5       | No       |            |

False positive rate: 20%

Word spoken - hey Travis

| Attempt | Detected | Confidence |
|---------|----------|------------|
| 1       | Yes      | 0.48       |
| 2       | Yes      | 0.33       |
| 3       | Yes      | 0.70       |
| 4       | Yes      | 0.94       |
| 5       | Yes      | 0.82       |

False positive rate: 100%

Word spoken - hey Marvis

| Attempt | Detected | Confidence |
|---------|----------|------------|
| 1       | No       |            |
| 2       | No       |            |
| 3       | No       |            |
| 4       | No       |            |
| 5       | No       |            |

False positive rate: 0%
Overall false positive rate: 40%

## Test 3 — Background noise, live voice

Background noise source: <https://youtu.be/WlZfNBRB-kM?si=6XuIpD-l7eFT2eCG>
RAM (script) current: 3.8 MB avg
RAM (script) peak: 6.0MB
RAM (system/RSS): 43.2 MB avg
CPU during listening: 13.1% avg / 18.4% peak

| Attempt | Detected | Confidence | Latency (ms) |
|---------|----------|------------|--------------|
| 1       | Yes      | 0.40       | 12.1         |
| 2       | No       |            |              |
| 3       | Yes      | 0.32       | 11.1         |
| 4       | Yes      | 0.33       | 9.0          |
| 5       | No       |            |              |
| 6       | Yes      | 0.48       | 5.8          |
| 7       | No       |            |              |
| 8       | Yes      | 0.37       | 6.8          |
| 9       | No       |            |              |
| 10      | Yes      | 0.39       | 8.2          |

Detection rate: 60%
Average confidence: 0.38
Average latency (ms): 8.8

## Test 4 — Audio playback, quiet room

RAM (python) current: 1.7 MB avg
RAM (python) peak: 4.8 MB
RAM (system/RSS): 155.5 MB avg
CPU at detection: 10.6% avg / 11.0% peak

| Attempt | Source                    | Detected | Confidence | Latency (ms) |
|---------|---------------------------|----------|------------|--------------|
| 1       | hey_jarvis_older_male_1   | Yes      | 0.35       | 6.0          |
| 2       | hey_jarvis_older_male_1   | Yes      | 0.32       | 5.8          |
| 3       | hey_jarvis_older_male_2   | Yes      | 0.98       | 6.0          |
| 4       | hey_jarvis_older_male_2   | Yes      | 0.97       | 6.3          |
| 5       | hey_jarvis_older_female_1 | Yes      | 0.47       | 6.5          |
| 6       | hey_jarvis_older_female_1 | Yes      | 0.95       | 5.6          |
| 7       | hey_jarvis_older_female_2 | Yes      | 0.98       | 6.0          |
| 8       | hey_jarvis_older_female_2 | Yes      | 0.40       | 6.1          |

Detection rate: 8/8 (100%)
Average confidence: 0.68
Average latency (ms): 6.0

## Threshold Comparison (quiet room, live voice)

Derived from existing Test 1 and Test 2 data by filtering results at each threshold.

| Threshold | Detection rate | False positive rate | Avg confidence | Avg latency (ms) |
|-----------|----------------|---------------------|----------------|------------------|
| 0.3       | 8/10 (80%)     | 40%                 | 0.55           | 9.4              |
| 0.5       | 4/10 (40%)     | 20%                 | 0.73           | 8.8              |
| 0.7       | 2/10 (20%)     | 13%                 | 0.92           | 9.4              |

## Issues observed

**Test 1:**

- Attempts 2 and 3 not detected. Likely caused by reduced voice volume during
  testing (5am, quiet environment, speaking under breath). This is relevant to
  the target user group — older adults may also speak more quietly or with
  reduced projection, which could contribute to missed detections.
- Confidence varied widely (0.32 to 0.99) across detected attempts at threshold
  0.3, suggesting detection is sensitive to voice volume and projection. Several
  attempts would have been missed at threshold 0.5 (attempts 4, 6, 8, 10).

**Test 2:**

- hey Travis triggered 5/5 false positives at threshold 0.3 with confidence
  ranging from 0.33 to 0.94, suggesting the model treats "Travis" as acoustically
  very similar to "Jarvis".
- hey Harris triggered 1/5 false positives at confidence 0.47, borderline at
  threshold 0.3 — would be eliminated at threshold 0.5.
- hey Marvis triggered 0/5 false positives, well distinguished by the model.
- Overall false positive rate of 40% at threshold 0.3 is high, driven almost
  entirely by hey Travis.

**Test 3:**

- Detection rate dropped from 80% (quiet room) to 60% in a noisy kitchen
  environment, with 4 missed detections.
- Average confidence dropped from 0.55 (quiet room) to 0.38 in noisy conditions,
  suggesting background noise meaningfully reduces model confidence.
- CPU usage spiked to 18.4% at peak compared to 9.1% in quiet conditions,
  indicating background noise increases processing load.
- All detections in noisy conditions had confidence below 0.5, meaning threshold
  0.5 would result in 0% detection rate in a kitchen environment — a critical
  risk given cooking is a primary use case.

**Test 4:**

- Female voices showed higher confidence variance than male voices.
  hey_jarvis_older_female_1 scored 0.47 and 0.95 across two identical plays,
  and hey_jarvis_older_female_2 scored 0.98 and 0.40 — a difference of 0.58
  within the same voice. Male voices were more consistent, with
  hey_jarvis_older_male_2 scoring 0.98 and 0.97 across both attempts.
- At threshold 0.5, 3 of the 8 playback attempts would have been missed
  (attempts 1, 2, and 8), all of which were either female voices or the lower
  confidence male voice. This suggests threshold 0.5 may be too conservative
  for older adult voices, particularly female voices.

## Recommendation

Threshold 0.3 is recommended for the MVP despite its higher false positive rate.
The threshold comparison shows that increasing to 0.5 halves the detection rate
(80% to 40%) and would result in 0% detection in noisy kitchen environments,
which is unacceptable given cooking is a primary use case. Threshold 0.7 reduces
detection to 20%, making it impractical for real use.

The hey Travis false positive risk at threshold 0.3 is noted but is considered
a lower priority than reliable detection for the target user group. This could
be mitigated in future by choosing a more acoustically distinct wake word or
by training a custom wake word.

openWakeWord with hey_jarvis_v0.1.onnx is suitable to proceed with in the
pipeline. The next step is VAD integration to capture utterance boundaries
after the wake word fires.
