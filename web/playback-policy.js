(function exposePlaybackPolicy(root) {
  "use strict";

  function shouldAutoPlayResponse({
    voiceOutput,
    audioAvailable,
    browserFallbackAvailable,
    confirmationRequired,
    speakConfirmations,
    interactionMode,
    isAudioTurn,
  }) {
    const serverAudioAvailable = voiceOutput && audioAvailable;
    if (!serverAudioAvailable && !browserFallbackAvailable) return false;
    if (confirmationRequired && !speakConfirmations) return false;
    if (interactionMode === "text_first") return false;
    if (interactionMode === "push_to_talk") return Boolean(isAudioTurn);
    return interactionMode === "voice_first" || interactionMode === "wake_word";
  }

  function isPlaybackBargeInCommand(command) {
    return command === "stop" || command === "pause" || command === "resume";
  }

  function shouldListenForVoiceCommands({
    capabilityEnabled,
    routineActive,
    playbackActive,
  }) {
    return Boolean(capabilityEnabled && (routineActive || playbackActive));
  }

  root.GranitePlaybackPolicy = Object.freeze({
    isPlaybackBargeInCommand,
    shouldAutoPlayResponse,
    shouldListenForVoiceCommands,
  });
}(globalThis));
