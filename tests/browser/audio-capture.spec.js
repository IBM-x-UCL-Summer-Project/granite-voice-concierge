const { expect, test } = require("@playwright/test");

async function installSyntheticMicrophone(page, { denied = false } = {}) {
  await page.route("**/web/audio-test-harness.html", (route) => route.fulfill({
    contentType: "text/html",
    body: "<!doctype html><title>Audio capture test</title>",
  }));
  await page.goto("/web/audio-test-harness.html");
  await page.evaluate(async ({ denyAccess }) => {
    const sourceContext = new AudioContext();
    await sourceContext.resume();
    const oscillator = sourceContext.createOscillator();
    const gain = sourceContext.createGain();
    const destination = sourceContext.createMediaStreamDestination();
    oscillator.frequency.value = 440;
    gain.gain.value = 0.1;
    oscillator.connect(gain).connect(destination);
    oscillator.start();

    let deviceId = "synthetic-a";
    const openedTracks = [];
    const requestedConstraints = [];
    const mediaDevices = {
      getSupportedConstraints: () => ({
        deviceId: true,
        channelCount: true,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      }),
      getUserMedia: async (constraints) => {
        requestedConstraints.push(structuredClone(constraints));
        if (denyAccess) {
          throw new DOMException("Permission denied for test", "NotAllowedError");
        }
        const stream = destination.stream.clone();
        const track = stream.getAudioTracks()[0];
        const nativeSettings = track.getSettings.bind(track);
        track.getSettings = () => ({ ...nativeSettings(), deviceId });
        openedTracks.push(track);
        return stream;
      },
      enumerateDevices: async () => [
        { kind: "audioinput", deviceId, label: `Synthetic ${deviceId}` },
      ],
      addEventListener: () => {},
    };
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: mediaDevices,
    });
    window.diagnostics = { info() {}, warning() {}, error() {} };
    window.state = { recorder: null, wakeWord: {}, voiceCommands: {} };
    window.syntheticMicrophone = {
      openedTracks,
      requestedConstraints,
      select(nextDeviceId) { deviceId = nextDeviceId; },
      close: async () => {
        oscillator.stop();
        await sourceContext.close();
      },
    };
  }, { denyAccess: denied });
  await page.addScriptTag({ url: "/web/audio-capture.js" });
}

test("captures synthetic audio through AudioWorklet at 16 kHz", async ({ page }) => {
  await installSyntheticMicrophone(page);
  await page.evaluate(async () => {
    window.receivedAudio = [];
    window.activeCapture = await openMicrophoneCapture({
      microphoneId: "synthetic-a",
      purpose: "browser_test",
      onSamples: (samples) => window.receivedAudio.push(Array.from(samples)),
    });
  });

  await expect.poll(() => page.evaluate(() => window.receivedAudio.length)).toBeGreaterThan(2);
  const result = await page.evaluate(async () => {
    const settings = window.activeCapture.settings;
    await window.activeCapture.stop();
    await window.syntheticMicrophone.close();
    return {
      settings,
      constraints: window.syntheticMicrophone.requestedConstraints[0],
      chunks: window.receivedAudio,
      trackState: window.syntheticMicrophone.openedTracks[0].readyState,
    };
  });

  expect(result.settings.context_sample_rate).toBeGreaterThan(0);
  expect(result.settings.device_id).toBe("synthetic-a");
  expect(result.constraints.audio).toMatchObject({
    deviceId: { exact: "synthetic-a" },
    channelCount: { ideal: 1 },
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true,
  });
  expect(result.chunks.every((chunk) => chunk.length > 0 && chunk.length <= 320)).toBe(true);
  expect(result.chunks.slice(0, -1).every((chunk) => chunk.length === 320)).toBe(true);
  expect(
    result.chunks.some((chunk) => chunk.some((sample) => Math.abs(sample) > 0.01)),
  ).toBe(true);
  expect(result.trackState).toBe("ended");
});

test("switches devices by closing the old track before reopening", async ({ page }) => {
  await installSyntheticMicrophone(page);
  const result = await page.evaluate(async () => {
    const first = await openMicrophoneCapture({
      microphoneId: "synthetic-a",
      purpose: "device_a",
      onSamples: () => {},
    });
    await first.stop({ flush: false });
    window.syntheticMicrophone.select("synthetic-b");
    const second = await openMicrophoneCapture({
      microphoneId: "synthetic-b",
      purpose: "device_b",
      onSamples: () => {},
    });
    const secondSettings = second.settings;
    await second.stop({ flush: false });
    await window.syntheticMicrophone.close();
    return {
      constraints: window.syntheticMicrophone.requestedConstraints,
      states: window.syntheticMicrophone.openedTracks.map((track) => track.readyState),
      secondSettings,
    };
  });

  expect(result.constraints.map((item) => item.audio.deviceId.exact)).toEqual([
    "synthetic-a",
    "synthetic-b",
  ]);
  expect(result.states).toEqual(["ended", "ended"]);
  expect(result.secondSettings.device_id).toBe("synthetic-b");
});

test("reports denied microphone permission and leaves no capture running", async ({ page }) => {
  await installSyntheticMicrophone(page, { denied: true });
  const result = await page.evaluate(async () => {
    try {
      await openMicrophoneCapture({
        microphoneId: "default",
        purpose: "permission_test",
        onSamples: () => {},
      });
      return { errorName: null };
    } catch (error) {
      return {
        errorName: error.name,
        openedTracks: window.syntheticMicrophone.openedTracks.length,
      };
    } finally {
      await window.syntheticMicrophone.close();
    }
  });

  expect(result).toEqual({ errorName: "NotAllowedError", openedTracks: 0 });
});
