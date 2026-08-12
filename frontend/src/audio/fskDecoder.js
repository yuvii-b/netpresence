export class FSKDecoder {
  constructor() {
    this.audioCtx = null;
    this.stream = null;
    this.source = null;
    this.scriptNode = null;
    this.freq0 = 1900; // Frequency for Bit 0 (Hz)
    this.freq1 = 2400; // Frequency for Bit 1 (Hz)
    this.bitDuration = 0.18; // Match 180ms from fskEncoder.js
    this.isListening = false;
    this.sampleBuffer = [];
    this.oversampledBits = [];

    // Running averages for adaptive thresholding
    this.avg0 = 0.05;
    this.avg1 = 0.05;

    // States
    this.STATE_SEARCHING = 0;
    this.STATE_DECODING = 1;
    this.state = this.STATE_SEARCHING;

    this.endOversampleIndex = -1;
    this.decodeStartTime = 0;
    this.lengthDecoded = false;
    this.payloadLength = 0;
  }

  // Non-integer Goertzel algorithm to estimate power at target frequency
  goertzel(samples, sampleRate, targetFreq) {
    const N = samples.length;
    if (N === 0) return 0;
    const omega = (2 * Math.PI * targetFreq) / sampleRate;
    const coeff = 2 * Math.cos(omega);
    let sPrev = 0;
    let sPrev2 = 0;
    for (let i = 0; i < N; i++) {
      const s = samples[i] + coeff * sPrev - sPrev2;
      sPrev2 = sPrev;
      sPrev = s;
    }
    const power = sPrev2 * sPrev2 + sPrev * sPrev - coeff * sPrev * sPrev2;
    return power;
  }

  async startListening(onTokenDecoded, onDebug) {
    console.log('[FSKDecoder] Starting listener...');
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    this.audioCtx = new AudioContextClass();

    if (this.audioCtx.state === 'suspended') {
      await this.audioCtx.resume();
    }

    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
      },
    });

    const sampleRate = this.audioCtx.sampleRate;
    this.source = this.audioCtx.createMediaStreamSource(this.stream);
    
    // ScriptProcessorNode guarantees continuous non-overlapping audio samples
    this.scriptNode = this.audioCtx.createScriptProcessor(2048, 1, 1);
    
    this.source.connect(this.scriptNode);
    this.scriptNode.connect(this.audioCtx.destination);

    this.isListening = true;
    this.sampleBuffer = [];
    this.oversampledBits = [];
    this.state = this.STATE_SEARCHING;
    this.avg0 = 0.05;
    this.avg1 = 0.05;

    let lastDebugTime = 0;

    this.scriptNode.onaudioprocess = (audioProcessingEvent) => {
      if (!this.isListening) return;

      const inputBuffer = audioProcessingEvent.inputBuffer;
      const inputData = inputBuffer.getChannelData(0);

      // Append new samples to buffer
      for (let i = 0; i < inputData.length; i++) {
        this.sampleBuffer.push(inputData[i]);
      }

      // Limit buffer size to prevent memory leaks
      if (this.sampleBuffer.length > 50000) {
        this.sampleBuffer = this.sampleBuffer.slice(-25000);
      }

      const W = Math.round(this.bitDuration * sampleRate);
      const hop = Math.round(W / 4);

      // Slide a window of size W by hop increments
      while (this.sampleBuffer.length >= W) {
        const windowSamples = this.sampleBuffer.slice(0, W);
        this.sampleBuffer.splice(0, hop);

        const power0 = this.goertzel(windowSamples, sampleRate, this.freq0);
        const power1 = this.goertzel(windowSamples, sampleRate, this.freq1);

        // Update running averages only while searching, to prevent AGC drift during unbalanced payloads
        if (this.state === this.STATE_SEARCHING) {
          this.avg0 = this.avg0 * 0.99 + power0 * 0.01;
          this.avg1 = this.avg1 * 0.99 + power1 * 0.01;
        }

        const safeAvg0 = Math.max(this.avg0, 0.005);
        const safeAvg1 = Math.max(this.avg1, 0.005);

        const normPower0 = power0 / safeAvg0;
        const normPower1 = power1 / safeAvg1;

        const now = performance.now();
        if (now - lastDebugTime > 300) {
          if (typeof onDebug === 'function') {
            onDebug({
              val0: power0,
              val1: power1,
              maxVal: Math.max(power0, power1),
              bitBufferLength: this.oversampledBits.length
            });
          }
          lastDebugTime = now;
        }

        const bit = normPower1 > normPower0 ? 1 : 0;
        this.oversampledBits.push(bit);

        // Keep oversample bit array length capped
        if (this.oversampledBits.length > 200) {
          this.oversampledBits.shift();
          if (this.state === this.STATE_DECODING) {
            this.endOversampleIndex--;
          }
        }

        if (this.state === this.STATE_SEARCHING) {
          // Convert oversampled bits to run-length representation
          const runs = [];
          for (let i = 0; i < this.oversampledBits.length; i++) {
            const val = this.oversampledBits[i];
            if (runs.length === 0 || runs[runs.length - 1].value !== val) {
              runs.push({ value: val, length: 1, endIndex: i });
            } else {
              runs[runs.length - 1].length++;
              runs[runs.length - 1].endIndex = i;
            }
          }

          // Search from the end for 8 alternating runs matching the preamble (10101010)
          const R = runs.length;
          let foundPreamble = false;
          let matchedEndIndex = -1;

          for (let j = R - 8; j >= 0; j--) {
            if (
              runs[j].value === 1 &&
              runs[j+1].value === 0 &&
              runs[j+2].value === 1 &&
              runs[j+3].value === 0 &&
              runs[j+4].value === 1 &&
              runs[j+5].value === 0 &&
              runs[j+6].value === 1 &&
              runs[j+7].value === 0
            ) {
              // Validate that run lengths are close to the expected oversample factor (4)
              let lengthsValid = true;
              for (let k = 0; k < 8; k++) {
                if (runs[j+k].length < 2 || runs[j+k].length > 7) {
                  lengthsValid = false;
                  break;
                }
              }

              if (lengthsValid) {
                foundPreamble = true;
                matchedEndIndex = runs[j+7].endIndex;
                break;
              }
            }
          }

          if (foundPreamble) {
            console.log('[FSKDecoder] Preamble matched! endOversampleIndex:', matchedEndIndex);
            this.state = this.STATE_DECODING;
            this.endOversampleIndex = matchedEndIndex;
            this.decodeStartTime = Date.now();
            this.lengthDecoded = false;
            this.payloadLength = 0;
          }
        }

        if (this.state === this.STATE_DECODING) {
          // Timeout if decoding hangs for too long
          if (Date.now() - this.decodeStartTime > 10000) {
            console.log('[FSKDecoder] Packet decoding timed out.');
            this.state = this.STATE_SEARCHING;
            this.oversampledBits = [];
            continue;
          }

          if (!this.lengthDecoded) {
            // Wait for 8 bits of length byte (sampled in the middle of each bit period)
            const requiredLength = this.endOversampleIndex + 1 + 8 * 4;
            if (this.oversampledBits.length >= requiredLength) {
              let length = 0;
              for (let i = 0; i < 8; i++) {
                const bitIdx = this.endOversampleIndex + 2 + i * 4;
                const sum = this.oversampledBits[bitIdx - 1] + this.oversampledBits[bitIdx] + this.oversampledBits[bitIdx + 1];
                const bit = sum >= 2 ? 1 : 0;
                length = (length << 1) | bit;
              }

              if (length > 0 && length <= 16) {
                console.log('[FSKDecoder] Decoded length byte:', length);
                this.payloadLength = length;
                this.lengthDecoded = true;
              } else {
                console.log('[FSKDecoder] Invalid length decoded:', length, '. Resetting.');
                this.state = this.STATE_SEARCHING;
                this.oversampledBits = [];
              }
            }
          } else {
            // Wait for full payload bits
            const requiredLength = this.endOversampleIndex + 1 + (8 + this.payloadLength * 8) * 4;
            if (this.oversampledBits.length >= requiredLength) {
              const payloadBytes = [];
              for (let c = 0; c < this.payloadLength; c++) {
                let byte = 0;
                for (let b = 0; b < 8; b++) {
                  const bitIdx = this.endOversampleIndex + 2 + (8 + c * 8 + b) * 4;
                  const sum = this.oversampledBits[bitIdx - 1] + this.oversampledBits[bitIdx] + this.oversampledBits[bitIdx + 1];
                  const bit = sum >= 2 ? 1 : 0;
                  byte = (byte << 1) | bit;
                }
                payloadBytes.push(byte);
              }

              try {
                const decodedStr = new TextDecoder().decode(new Uint8Array(payloadBytes));
                console.log('[FSKDecoder] Successfully decoded token string:', decodedStr);
                if (decodedStr && typeof onTokenDecoded === 'function') {
                  onTokenDecoded(decodedStr);
                }
              } catch (e) {
                console.error('[FSKDecoder] FSK decoding error:', e);
              }

              // Return to searching for next token
              this.state = this.STATE_SEARCHING;
              this.oversampledBits = [];
            }
          }
        }
      }
    };
  }

  stop() {
    console.log('[FSKDecoder] stop() called.');
    this.isListening = false;
    this.sampleBuffer = [];
    this.oversampledBits = [];
    this.state = this.STATE_SEARCHING;

    if (this.scriptNode) {
      try {
        this.scriptNode.disconnect();
      } catch (e) {}
      this.scriptNode = null;
    }
    if (this.source) {
      try {
        this.source.disconnect();
      } catch (e) {}
      this.source = null;
    }
    if (this.stream) {
      try {
        this.stream.getTracks().forEach((track) => track.stop());
      } catch (e) {}
      this.stream = null;
    }
    if (this.audioCtx) {
      try {
        this.audioCtx.close();
      } catch (e) {}
      this.audioCtx = null;
    }
  }
}
