export const ALPHABET = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ';
const BASE_FREQ = 1000;
const FREQ_STEP = 60;
const START_FREQ = 800;
const END_FREQ = 900;
const TONE_MS = 400;
const GAP_MS = 150;

export function freqForChar(c) {
  const idx = ALPHABET.indexOf(c.toUpperCase());
  if (idx === -1) throw new Error(`Unsupported token char: ${c}`);
  return BASE_FREQ + idx * FREQ_STEP;
}

export class ToneEncoder {
  constructor() {
    this.audioCtx = null;
    this.playing = false;
  }

  async initContext() {
    if (!this.audioCtx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      this.audioCtx = new AC();
    }
    if (this.audioCtx.state === 'suspended') await this.audioCtx.resume();

    // iOS Safari unlock: play one silent buffer so the audio hardware is fully
    // enabled. resume() alone is insufficient on older iOS versions.
    if (!this._unlocked) {
      const buffer = this.audioCtx.createBuffer(1, 1, 22050);
      const src = this.audioCtx.createBufferSource();
      src.buffer = buffer;
      src.connect(this.audioCtx.destination);
      src.start(0);
      this._unlocked = true;
    }
  }

  _playTone(freq, startTime, durationMs) {
    const osc = this.audioCtx.createOscillator();
    const gain = this.audioCtx.createGain();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(freq, startTime);
    gain.gain.setValueAtTime(0, startTime);
    gain.gain.linearRampToValueAtTime(0.7, startTime + 0.02);
    gain.gain.linearRampToValueAtTime(0.7, startTime + durationMs / 1000 - 0.02);
    gain.gain.linearRampToValueAtTime(0, startTime + durationMs / 1000);
    osc.connect(gain);
    gain.connect(this.audioCtx.destination);
    osc.start(startTime);
    osc.stop(startTime + durationMs / 1000);
  }

  async playToken(token) {
    await this.initContext();
    this.playing = true;
    let t = this.audioCtx.currentTime + 0.1;

    this._playTone(START_FREQ, t, TONE_MS);
    t += (TONE_MS + GAP_MS) / 1000;

    for (const ch of token) {
      if (!this.playing) break;
      this._playTone(freqForChar(ch), t, TONE_MS);
      t += (TONE_MS + GAP_MS) / 1000;
    }

    this._playTone(END_FREQ, t, TONE_MS);
    t += (TONE_MS + GAP_MS) / 1000;

    return (t - this.audioCtx.currentTime) * 1000; // total ms
  }

  stop() {
    this.playing = false;
    if (this.audioCtx) {
      this.audioCtx.close();
      this.audioCtx = null;
    }
  }
}
