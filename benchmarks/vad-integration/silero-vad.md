# VAD Integration Benchmark — Silero VAD

## Device

- Date: 19-06-2026
- Machine: MacBook Pro (14-inch, 2021)
- Chip: Apple M1 Pro
- OS: macOS 26.2
- Python: 3.9
- Tool: Silero VAD
- Backend: PyTorch (CPU)

## Configuration

- THRESHOLD: 0.5
- MIN_SILENCE_DURATION_MS: 300 (reduced from 500ms default — felt slow in
  practice, 300ms provides more natural conversational pacing)
- SPEECH_PAD_MS: 100
- CHUNK: 512 samples (~32ms at 16kHz)

## Notes on measurements

- Utterance duration is measured from `"start"` VAD event to `"end"` VAD event.
  Excludes time before speech begins but is consistent across runs.
- RAM (python) is measured via tracemalloc — Python-level allocations only,
  excludes native libraries such as PyTorch and PyAudio.
- RAM (system/RSS) is measured via psutil RSS (Resident Set Size) — total memory
  the OS has allocated to the process, including native libraries.
- CPU is measured via psutil `cpu_percent()` — the value represents average CPU
  usage of the process since the warm-up call at the start of `capture_utterance`.

## Test 1 — Short utterance, quiet room

Single short sentence spoken clearly after VAD starts listening.

RAM (python) current: 0.1MB
RAM (python) peak: 0.1MB
RAM (system/RSS): 178.2 MB avg
CPU at detection: 6.9% avg / 8.6% peak

| Attempt | Utterance            | Captured | Duration (ms) | Samples |
|---------|----------------------|----------|---------------|---------|
| 1       | "what is the time"   | Yes      | 1340.7        | 21504   |
| 2       | "what is the time"   | Yes      | 1314.8        | 20992   |
| 3       | "what is the time"   | Yes      | 1375.4        | 22016   |
| 4       | "what is the time"   | Yes      | 1353.5        | 21504   |
| 5       | "what is the time"   | Yes      | 1315.0        | 20992   |

Capture rate: 5/5 (100%)
Average duration (ms): 1339.9
Average samples: 21401.6

## Test 2 — Mid-utterance pause

RAM (python) current: 0.1 MB avg
RAM (python) peak: 0.2 MB
RAM (system/RSS): 204.9 MB avg
CPU at detection: 7.9% avg / 9.2% peak

| Attempt | Utterance                          | Cut off early | Duration (ms) |
|---------|------------------------------------|---------------|---------------|
| 1       | "remind me to... take medication"  | Yes           | 1785.5        |
| 2       | "remind me to... take medication"  | No            | 3040.1        |
| 3       | "remind me to... take medication"  | Yes           | 1760.1        |
| 4       | "remind me to... take medication"  | Yes           | 1819.8        |
| 5       | "remind me to... take medication"  | No            | 3875.8        |

Early cut-off rate: 3/5 (60%)
Average duration (ms): 2456.3

## Test 3 — Silence timeout

| Attempt | Behaviour observed                              | Duration before timeout (ms) |
|---------|-------------------------------------------------|------------------------------|
| 1       | Hung indefinitely — required KeyboardInterrupt  | N/A                          |
| 2       | Hung indefinitely — required KeyboardInterrupt  | N/A                          |
| 3       | Hung indefinitely — required KeyboardInterrupt  | N/A                          |

Update: Now timesout after 5 seconds.

## Test 4 — Background noise, short utterance

Background noise source: <https://youtu.be/WlZfNBRB-kM?si=6XuIpD-l7eFT2eCG>

RAM (python) current: 0.1 MB avg
RAM (python) peak: 0.1 MB
RAM (system/RSS): 205.4 MB avg
CPU at detection: 8.2% avg / 9.3% peak

| Attempt | Utterance          | Captured | Duration (ms) | Samples |
|---------|--------------------|----------|---------------|---------|
| 1       | "what is the time" | Yes      | 1499.3        | 24064   |
| 2       | "what is the time" | Yes      | 1628.1        | 26112   |
| 3       | "what is the time" | Yes      | 1538.6        | 24576   |
| 4       | "what is the time" | Yes      | 1472.8        | 23552   |
| 5       | "what is the time" | Yes      | 1539.0        | 24576   |

Capture rate: 5/5 (100%)
Average duration (ms): 1535.6
Average samples: 24576

```markdown
## Issues observed

**Test 1:**

- 5/5 captures with consistent duration variance of only 60ms across attempts,
  suggesting VAD reliably and repeatably detects utterance boundaries for short
  clear speech in quiet conditions.

**Test 2:**

- MIN_SILENCE_BEFORE_UTTERANCE_END_MS of 300ms caused early cut-offs in 3/5
  attempts when a mid-utterance pause was introduced. Attempts that were not
  cut off had durations of 3040ms and 3875ms, suggesting the pause needed to
  exceed 300ms to avoid early termination.
- This presents a meaningful accessibility risk — older adults tend to pause
  more frequently mid-utterance, making 300ms potentially too aggressive for
  the target user group.
- A dynamic silence threshold based on context mode may be worth investigating,
  for example a longer threshold in Home mode where conversational speech is
  expected, and a shorter threshold in Shopping mode where commands are brief.

**Test 3:**

- No silence timeout was implemented in the initial script. If the user stays
  silent after the wake word fires, the VAD loop hung indefinitely and required
  a KeyboardInterrupt to exit.
- A MAX_SPEECH_START_WAIT_S timeout of 5 seconds was added to resolve
  this. The system now exits the VAD loop cleanly and prints a timeout message
  if no speech is detected within the window.

**Test 4:**

- Capture rate held at 5/5 (100%) in noisy kitchen conditions, with only a
  modest increase in average duration compared to quiet room (1535.6ms vs
  1339.9ms, a difference of ~196ms).
- VAD proved more robust to background noise than openWakeWord — the wake word
  detector dropped from 80% to 60% detection rate under the same noise source,
  while VAD maintained 100% capture rate.
- CPU usage remained stable between quiet (8.6% peak) and noisy (9.3% peak)
  conditions, suggesting background noise does not meaningfully increase
  processing load for VAD.

## Recommendation

Silero VAD is suitable for the MVP pipeline. It captures utterance boundaries
reliably in both quiet and noisy conditions, has negligible Python-level memory
usage (0.1MB), and maintains low CPU overhead (~8-9%) during continuous
listening.

The primary concern is the mid-utterance pause cut-off rate of 60% at
MIN_SILENCE_BEFORE_UTTERANCE_END_MS of 300ms. For the MVP, increasing this
to 500ms for Home and Cooking modes is recommended to better support the target
user group, accepting the slightly slower conversational pacing as a trade-off.
Shopping and Driving modes can retain 300ms given commands in those contexts
are expected to be short and direct.

The silence timeout (MAX_SPEECH_START_WAIT_S of 5 seconds) resolves the
indefinite hang issue and should be retained in the integrated pipeline. A
spoken prompt such as "Sorry, I didn't catch that" should be added when the
timeout fires before returning to wake word listening.

Next step is integrating VAD with the wake word detector so the full
wake word → VAD → STT pipeline can be tested end to end.
