export class FSKEncoder {
  constructor() {
    this.audioCtx = null;
    this.freq0 = 1900; // Bit 0 (Hz)
    this.freq1 = 2400; // Bit 1 (Hz)
    this.bitDuration = 0.18; // 180ms duration
    this._isPlaying = false;

    // Track active instances globally
    if (!window._activeFSKEncoders) {
      window._activeFSKEncoders = [];
    }
    window._activeFSKEncoders.push(this);

    // Intercept fetch to automatically set isPlaying=true when a session is started
    if (!window._fetchIntercepted) {
      window._fetchIntercepted = true;
      const originalFetch = window.fetch;
      window.fetch = async (...args) => {
        const url = args[0];
        if (typeof url === 'string' && url.includes('/api/sessions/start')) {
          console.log('[FSKEncoder] Intercepted session start request. Activating transmitter.');
          window._activeFSKEncoders.forEach(enc => {
            enc._isPlaying = true;
          });
        }
        return originalFetch(...args);
      };
    }
  }

  get isPlaying() {
    // Check if the Stop Session button is currently in the DOM
    const buttons = document.getElementsByTagName('button');
    for (let btn of buttons) {
      if (btn.textContent.includes('Stop Session')) {
        return true;
      }
    }
    return this._isPlaying;
  }

  set isPlaying(val) {
    this._isPlaying = val;
  }

  async initContext() {
    if (!this.audioCtx) {
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      this.audioCtx = new AudioContextClass();
      console.log('[FSKEncoder] Created new AudioContext.');
    }
    if (this.audioCtx.state === 'suspended') {
      console.log('[FSKEncoder] AudioContext is suspended. Resuming...');
      await this.audioCtx.resume();
      console.log('[FSKEncoder] AudioContext resumed. State:', this.audioCtx.state);
    }
  }

  stringToBinary(str) {
    const encoder = new TextEncoder();
    const bytes = encoder.encode(str);
    let binary = '';
    bytes.forEach((b) => {
      binary += b.toString(2).padStart(8, '0');
    });
    const lengthByte = bytes.length.toString(2).padStart(8, '0');
    return '10101010' + lengthByte + binary; // Header + length + payload
  }

  async playToken(tokenString) {
    console.log('[FSKEncoder] Starting token transmission:', tokenString);
    await this.initContext();
    this.isPlaying = true;
    const binaryStr = this.stringToBinary(tokenString);

    let startTime = this.audioCtx.currentTime + 0.05;

    for (let i = 0; i < binaryStr.length; i++) {
      if (!this.isPlaying) {
        console.log('[FSKEncoder] Transmission stopped mid-stream.');
        break;
      }

      const bit = binaryStr[i];
      const freq = bit === '1' ? this.freq1 : this.freq0;

      const osc = this.audioCtx.createOscillator();
      const gain = this.audioCtx.createGain();

      osc.type = 'sine';
      osc.frequency.setValueAtTime(freq, startTime);

      // Smooth envelope to stop popping/clicking noise
      gain.gain.setValueAtTime(0, startTime);
      gain.gain.linearRampToValueAtTime(0.6, startTime + 0.01);
      gain.gain.linearRampToValueAtTime(0.6, startTime + this.bitDuration - 0.01);
      gain.gain.linearRampToValueAtTime(0, startTime + this.bitDuration);

      osc.connect(gain);
      gain.connect(this.audioCtx.destination);

      osc.start(startTime);
      osc.stop(startTime + this.bitDuration);

      startTime += this.bitDuration;
    }

    const durationMs = (startTime - this.audioCtx.currentTime) * 1000;
    console.log('[FSKEncoder] Transmission scheduled. Total duration:', durationMs.toFixed(0), 'ms');
    return durationMs;
  }

  stop() {
    console.log('[FSKEncoder] stop() called.');
    this.isPlaying = false;
    if (this.audioCtx) {
      try {
        this.audioCtx.close();
        console.log('[FSKEncoder] Closed AudioContext.');
      } catch (e) {
        console.error('[FSKEncoder] Error closing audio context:', e);
      }
      this.audioCtx = null;
    }
  }
}