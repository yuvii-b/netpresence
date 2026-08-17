import { freqForChar, ALPHABET } from './toneEncoder';
import { isIOS, getOS, getDeviceType } from './platform';

const START_FREQ = 800;
const END_FREQ = 900;
const CANDIDATES = ALPHABET.split('').map(freqForChar).concat([START_FREQ, END_FREQ]);
const WINDOW_MS = 100;      // small analysis window, no need to match tone length
const DEBOUNCE_MS = 250;    // min gap before accepting the same symbol again

// iOS can't fully disable its own AGC/noise suppression via getUserMedia
// constraints, which lowers the SNR of a received tone — so it needs much
// looser thresholds than Android/desktop to detect the same physical sound.
const THRESHOLDS = {
  ios: { power: 1.05, abs: 0.000001 },
  default: { power: 4.0, abs: 0.0001 },
};

export class ToneDecoder {
  constructor() {
    this.audioCtx = null;
    this.stream = null;
    this.node = null;
    this.buffer = [];
    this.listening = false;
    this.started = false;
    this.tokenChars = [];
    this.armed = true;

    this.os = getOS();
    this.deviceType = getDeviceType();
    const profile = isIOS() ? THRESHOLDS.ios : THRESHOLDS.default;
    this.powerThreshold = profile.power;
    this.absPowerThreshold = profile.abs;
  }

  goertzel(samples, sampleRate, freq) {
    const N = samples.length;
    const omega = (2 * Math.PI * freq) / sampleRate;
    const coeff = 2 * Math.cos(omega);
    let s1 = 0, s2 = 0;
    for (let i = 0; i < N; i++) {
      const s = samples[i] + coeff * s1 - s2;
      s2 = s1; s1 = s;
    }
    return s2 * s2 + s1 * s1 - coeff * s1 * s2;
  }

  async startListening(onToken, onDebug) {
    const AC = window.AudioContext || window.webkitAudioContext;
    this.audioCtx = new AC();
    if (this.audioCtx.state === 'suspended') await this.audioCtx.resume();

    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
    });

    const sampleRate = this.audioCtx.sampleRate;
    const source = this.audioCtx.createMediaStreamSource(this.stream);
    this.node = this.audioCtx.createScriptProcessor(2048, 1, 1);
    source.connect(this.node);
    this.node.connect(this.audioCtx.destination);

    this.listening = true;
    this.started = false;
    this.tokenChars = [];
    this.buffer = [];
    this.armed = true;

    const windowSize = Math.round((WINDOW_MS / 1000) * sampleRate);

    this.node.onaudioprocess = (e) => {
      if (!this.listening) return;
      const data = e.inputBuffer.getChannelData(0);
      for (let i = 0; i < data.length; i++) this.buffer.push(data[i]);
      if (this.buffer.length > windowSize * 3) this.buffer = this.buffer.slice(-windowSize * 2);
      if (this.buffer.length < windowSize) return;

      const window = this.buffer.slice(-windowSize);

      let bestFreq = null, bestPower = 0;
      let totalPower = 0;
      for (const f of CANDIDATES) {
        const p = this.goertzel(window, sampleRate, f);
        totalPower += p;
        if (p > bestPower) { bestPower = p; bestFreq = f; }
      }

      const avgPower = totalPower / CANDIDATES.length;
      const snr = bestPower / (avgPower || 1);
      const normPower = bestPower / (window.length * window.length);

      if (onDebug) onDebug({ bestFreq, bestPower: snr });

      if (snr < this.powerThreshold || normPower < this.absPowerThreshold) {
        this.armed = true; // silence seen — arm for the next tone
        return;
      }

      if (!this.armed) return; // still inside the same tone as last time — ignore
      this.armed = false;      // consume this tone, don't re-register until silence

      if (bestFreq === START_FREQ) {
        this.started = true;
        this.tokenChars = [];
        return;
      }
      if (!this.started) return;

      if (bestFreq === END_FREQ) {
        const token = this.tokenChars.join('');
        this.started = false;
        this.tokenChars = [];
        if (token && onToken) onToken(token);
        return;
      }

      const idx = ALPHABET.split('').map(freqForChar).indexOf(bestFreq);
      if (idx !== -1) this.tokenChars.push(ALPHABET[idx]);
    };
  }

  stop() {
    this.listening = false;
    if (this.node) { this.node.disconnect(); this.node = null; }
    if (this.stream) { this.stream.getTracks().forEach(t => t.stop()); this.stream = null; }
    if (this.audioCtx) { this.audioCtx.close(); this.audioCtx = null; }
  }
}
