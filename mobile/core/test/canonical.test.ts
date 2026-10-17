import { createPublicKey, verify } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import vectors from '../../../docs/test-vectors.json';
import { checkinMessage, registerMessage, reportMessage } from '../src/canonical';

// docs/test-vectors.json is produced by the SERVER's own code (backend/tools/make_vectors.py).
describe('canonical messages match the server byte-for-byte', () => {
  it('register + checkin', () => {
    expect(registerMessage('21CT042', 'Redmi Note 9')).toBe(vectors.messages.register);
    expect(checkinMessage('S-1a2b3c4d5e', '9f8e7d6c5b4a39281706f5e4d3c2b1a0')).toBe(vectors.messages.checkin);
  });
  it('report: sorted rows, compact JSON, ties broken by rssi then count', () => {
    expect(reportMessage('S-1a2b3c4d5e', '21CT042', vectors.neighbours)).toBe(vectors.messages.report);
    // order of the input list must not matter
    expect(reportMessage('S-1a2b3c4d5e', '21CT042', [...vectors.neighbours].reverse())).toBe(vectors.messages.report);
  });
});

describe('signatures made by the Python server code verify in Node', () => {
  const key = createPublicKey({ key: Buffer.from(vectors.public_key_spki_b64, 'base64'), format: 'der', type: 'spki' });
  for (const k of ['register', 'checkin', 'report'] as const) {
    it(k, () => {
      const ok = verify('sha256', Buffer.from(vectors.messages[k]), { key, dsaEncoding: 'der' }, Buffer.from(vectors.signatures_by_python[k], 'base64'));
      expect(ok).toBe(true);
    });
  }
  it('a tampered message does not verify', () => {
    const ok = verify('sha256', Buffer.from(vectors.messages.report + ' '), { key, dsaEncoding: 'der' }, Buffer.from(vectors.signatures_by_python.report, 'base64'));
    expect(ok).toBe(false);
  });
});
