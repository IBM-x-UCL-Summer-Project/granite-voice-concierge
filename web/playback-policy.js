(function exposePlaybackPolicy(root) {
  "use strict";

  function shouldAutoPlayResponse({
    voiceOutput,
    audioAvailable,
    confirmationRequired,
    speakConfirmations,
    interactionMode,
    isAudioTurn,
  }) {
    if (!voiceOutput || !audioAvailable) return false;
    if (confirmationRequired && !speakConfirmations) return false;
    if (interactionMode === "text_first") return false;
    if (interactionMode === "push_to_talk") return Boolean(isAudioTurn);
    return interactionMode === "voice_first";
  }

  root.GranitePlaybackPolicy = Object.freeze({ shouldAutoPlayResponse });
}(globalThis));
