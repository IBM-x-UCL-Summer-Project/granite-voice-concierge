(function exposeWakeCapturePolicy(root) {
  "use strict";

  function prepareWakeCapture({
    chunks,
    sampleRate,
    captureStartedAt,
    deferSpeechArm,
    armDelayMs,
  }) {
    const retainedChunks = chunks.filter((chunk) => chunk.length);
    const retainedSamples = retainedChunks.reduce(
      (total, chunk) => total + chunk.length,
      0,
    );
    const preRollMs = (retainedSamples / sampleRate) * 1000;
    return {
      retainedChunks,
      preRollMs,
      commandStartedAt: captureStartedAt - preRollMs,
      speechArmedAt: captureStartedAt + (deferSpeechArm ? armDelayMs : 0),
    };
  }

  function speechCanStart({ now, speechArmedAt, rms, speechThreshold }) {
    return now >= speechArmedAt && rms >= speechThreshold;
  }

  root.GraniteWakeCapturePolicy = Object.freeze({
    prepareWakeCapture,
    speechCanStart,
  });
}(globalThis));
