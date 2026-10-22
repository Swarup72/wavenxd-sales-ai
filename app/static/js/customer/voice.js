/**
 * WaveNxD AI Sales Representative - Voice Recording, Audio Upload & Speech Synthesis
 */

import { state } from '../core/state.js';
import { apiRequest } from '../core/api.js';
import { showToast } from '../ui/notifications.js';

let audioMeterCtx = null;
let audioMeterAnalyser = null;
let audioMeterAnimId = null;

function cleanupAudioMeter() {
  if (audioMeterAnimId) {
    cancelAnimationFrame(audioMeterAnimId);
    audioMeterAnimId = null;
  }
  if (audioMeterCtx) {
    try {
      audioMeterCtx.close();
    } catch (_) {}
    audioMeterCtx = null;
    audioMeterAnalyser = null;
  }
  const meter = document.getElementById('recAudioLevel');
  if (meter) {
    meter.style.width = '0%';
    meter.setAttribute('aria-valuenow', '0');
  }
}

export async function startRecording(timerEl, recordingBarEl) {
  if (state.isRecording) return;

  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    showToast('Audio recording is not supported in this browser.', 'error');
    return;
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    state.mediaRecorder = new MediaRecorder(stream);
    state.audioChunks = [];

    state.mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) state.audioChunks.push(e.data);
    };

    // Attach AudioContext volume meter for accessible live feedback
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (AudioCtx) {
        audioMeterCtx = new AudioCtx();
        const source = audioMeterCtx.createMediaStreamSource(stream);
        audioMeterAnalyser = audioMeterCtx.createAnalyser();
        audioMeterAnalyser.fftSize = 256;
        source.connect(audioMeterAnalyser);

        const dataArray = new Uint8Array(audioMeterAnalyser.frequencyBinCount);
        const meter = document.getElementById('recAudioLevel');

        const updateMeter = () => {
          if (!state.isRecording) {
            cleanupAudioMeter();
            return;
          }
          audioMeterAnalyser.getByteFrequencyData(dataArray);
          let sum = 0;
          for (let i = 0; i < dataArray.length; i++) {
            sum += dataArray[i];
          }
          const avg = sum / dataArray.length;
          // Scale to 0-100%
          const pct = Math.min(100, Math.round((avg / 128) * 100));
          if (meter) {
            meter.style.width = `${pct}%`;
            meter.setAttribute('aria-valuenow', String(pct));
          }
          audioMeterAnimId = requestAnimationFrame(updateMeter);
        };
        updateMeter();
      }
    } catch (meterErr) {
      console.warn('AudioContext volume meter initialization skipped:', meterErr);
    }

    state.mediaRecorder.start();
    state.isRecording = true;
    state.recordingStartTime = Date.now();

    if (recordingBarEl) recordingBarEl.style.display = 'flex';

    if (timerEl) {
      timerEl.textContent = '00:00';
      clearInterval(state.recordingTimerInterval);
      state.recordingTimerInterval = setInterval(() => {
        const elapsedSec = Math.floor((Date.now() - state.recordingStartTime) / 1000);
        const mins = String(Math.floor(elapsedSec / 60)).padStart(2, '0');
        const secs = String(elapsedSec % 60).padStart(2, '0');
        timerEl.textContent = `${mins}:${secs}`;
      }, 1000);
    }
  } catch (err) {
    cleanupAudioMeter();
    showToast(`Microphone access denied: ${err.message}`, 'error');
    state.isRecording = false;
  }
}

export function cancelRecording(recordingBarEl) {
  cleanupAudioMeter();
  if (!state.isRecording || !state.mediaRecorder) return;

  try {
    state.mediaRecorder.stop();
    state.mediaRecorder.stream.getTracks().forEach((track) => track.stop());
  } catch (_) {}

  state.isRecording = false;
  state.audioChunks = [];
  clearInterval(state.recordingTimerInterval);

  if (recordingBarEl) recordingBarEl.style.display = 'none';
  showToast('Voice recording cancelled.', 'info');
}

export async function stopAndSubmitRecording(recordingBarEl, onTranscribedCallback) {
  cleanupAudioMeter();
  if (!state.isRecording || !state.mediaRecorder) return;

  const currentRecorder = state.mediaRecorder;

  return new Promise((resolve) => {
    currentRecorder.onstop = async () => {
      currentRecorder.stream.getTracks().forEach((track) => track.stop());
      state.isRecording = false;
      clearInterval(state.recordingTimerInterval);
      if (recordingBarEl) recordingBarEl.style.display = 'none';

      const audioBlob = new Blob(state.audioChunks, { type: 'audio/webm' });
      state.audioChunks = [];

      if (audioBlob.size < 500) {
        showToast('Recorded audio is too short.', 'warning');
        resolve();
        return;
      }

      await uploadAndProcessAudio(audioBlob, 'recorded_audio.webm', onTranscribedCallback);
      resolve();
    };

    currentRecorder.stop();
  });
}

export async function uploadAndProcessAudio(blobOrFile, filename, onTranscribedCallback) {
  if (!state.currentConversationId) {
    showToast('Please select or create a consultation first.', 'warning');
    return;
  }

  showToast('Transcribing audio via Groq Whisper...', 'info');

  const formData = new FormData();
  formData.append('file', blobOrFile, filename);

  try {
    const res = await apiRequest(`/customer/conversations/${state.currentConversationId}/voice-messages`, {
      method: 'POST',
      body: formData,
    });

    if (onTranscribedCallback && typeof onTranscribedCallback === 'function') {
      onTranscribedCallback(res);
    }
    showToast('Voice message transcribed and processed.', 'success');
  } catch (err) {
    showToast(`Voice message failed: ${err.message}`, 'error');
  }
}

export async function synthesizeAndPlayAudio(conversationId, messageId, buttonEl) {
  if (state.currentAudio && state.playingMessageId === messageId) {
    state.currentAudio.pause();
    state.currentAudio = null;
    state.playingMessageId = null;
    if (buttonEl) {
      buttonEl.classList.remove('playing');
      buttonEl.innerHTML = '<span>🔊 Listen</span>';
    }
    return;
  }

  if (state.currentAudio) {
    state.currentAudio.pause();
    state.currentAudio = null;
    state.playingMessageId = null;
    document.querySelectorAll('.btn-speak.playing').forEach((b) => {
      b.classList.remove('playing');
      b.innerHTML = '<span>🔊 Listen</span>';
    });
  }

  if (buttonEl) {
    buttonEl.classList.add('loading');
    buttonEl.innerHTML = '<span>⏳ Synthesizing...</span>';
  }

  try {
    const blob = await apiRequest(`/customer/conversations/${conversationId}/messages/${messageId}/speak`, {
      method: 'POST',
    });

    const audioUrl = URL.createObjectURL(blob);
    const audio = new Audio(audioUrl);
    state.currentAudio = audio;
    state.playingMessageId = messageId;

    if (buttonEl) {
      buttonEl.classList.remove('loading');
      buttonEl.classList.add('playing');
      buttonEl.innerHTML = '<span>⏸ Pause</span>';
    }

    audio.onended = () => {
      state.currentAudio = null;
      state.playingMessageId = null;
      if (buttonEl) {
        buttonEl.classList.remove('playing');
        buttonEl.innerHTML = '<span>🔊 Listen</span>';
      }
      URL.revokeObjectURL(audioUrl);
    };

    audio.onerror = () => {
      showToast('Error playing synthesized audio.', 'error');
      state.currentAudio = null;
      state.playingMessageId = null;
      if (buttonEl) {
        buttonEl.classList.remove('playing', 'loading');
        buttonEl.innerHTML = '<span>🔊 Listen</span>';
      }
    };

    await audio.play();
  } catch (err) {
    showToast(`TTS error: ${err.message}`, 'error');
    if (buttonEl) {
      buttonEl.classList.remove('loading', 'playing');
      buttonEl.innerHTML = '<span>🔊 Listen</span>';
    }
  }
}

// Global hook for test suites and inline handlers
if (typeof window !== 'undefined') {
  window.wavenxdPlayAudio = function (conversationId, messageId, buttonEl) {
    return synthesizeAndPlayAudio(conversationId, messageId, buttonEl);
  };
}
