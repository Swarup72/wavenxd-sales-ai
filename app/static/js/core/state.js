/**
 * WaveNxD AI Sales Representative - Central State Store
 */

export const state = {
  csrfToken: null,
  currentUser: null,
  conversations: [],
  currentConversationId: null,
  currentConversationDetail: null,
  assignedProducts: [],
  lastRecResult: null,

  // Voice recording state
  isRecording: false,
  mediaRecorder: null,
  audioChunks: [],
  recordingTimerInterval: null,
  recordingStartTime: null,

  // Text-to-speech audio state
  currentAudio: null,
  playingMessageId: null,
};

/**
 * Resets conversational state when switching consultations or signing out
 */
export function resetConversationState() {
  state.currentConversationId = null;
  state.currentConversationDetail = null;
  state.lastRecResult = null;
  if (state.currentAudio) {
    try {
      state.currentAudio.pause();
    } catch (_) {}
    state.currentAudio = null;
  }
  state.playingMessageId = null;
}

/**
 * Resets user session state upon logout
 */
export function resetSessionState() {
  state.currentUser = null;
  state.conversations = [];
  state.assignedProducts = [];
  resetConversationState();
}
