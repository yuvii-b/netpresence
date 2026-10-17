/** Node-only helpers for tests and tooling (NOT bundled into the phone app). */
import { createPrivateKey, createPublicKey, generateKeyPairSync, sign } from 'node:crypto';
import type { KeyStore, Radio, RadioSample } from './types';

export class NodeKeyStore implements KeyStore {
  private readonly priv = generateKeyPairSync('ec', { namedCurve: 'P-256' });
  async publicKeyB64() {
    return this.priv.publicKey.export({ type: 'spki', format: 'der' }).toString('base64');
  }
  async signB64(message: string) {
    return sign('sha256', Buffer.from(message, 'utf8'), { key: this.priv.privateKey, dsaEncoding: 'der' }).toString('base64');
  }
}

/** Replays a fixed list of advertisements as soon as the radio "starts". */
export class ReplayRadio implements Radio {
  started: { name: string; uuid: string } | null = null;
  stopped = 0;
  constructor(private readonly samples: RadioSample[]) {}
  async start(name: string, uuid: string, onSample: (s: RadioSample) => void) {
    this.started = { name, uuid };
    for (const s of this.samples) onSample(s);
  }
  async stop() {
    this.stopped++;
  }
}

export { createPrivateKey, createPublicKey };
