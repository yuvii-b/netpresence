/**
 * Vectors that tie the Python network simulator (backend/netsim) to this code.
 *  - collector-vectors.json : random sample streams -> exactly what NeighbourCollector reports
 *  - retry-vectors.json     : when submitReport tries again if every attempt fails at once
 * The committed files are checked here against the real TypeScript; backend/tests/netsim/test_m4_*.py checks the Python
 * port against the same files. Regenerate with:  UPDATE_VECTORS=1 npx vitest run test/netsim-vectors.test.ts
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { NeighbourCollector, MAX_NEIGHBOURS } from '../src/aggregate';
import { ApiError, NetPresenceApi, REQUEST_TIMEOUT_MS } from '../src/api';
import { submitReport } from '../src/session';
import type { Clock, Joined, KeyStore } from '../src/types';

const DIR = join(dirname(fileURLToPath(import.meta.url)), 'fixtures');
const FILE_C = join(DIR, 'collector-vectors.json');
const FILE_R = join(DIR, 'retry-vectors.json');

function mulberry32(a: number) {
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function collectorVectors() {
  const rnd = mulberry32(12345);
  const cases = [];
  for (let k = 0; k < 80; k++) {
    const self = '0000abcd';
    const peers = 1 + Math.floor(rnd() * (k < 5 ? MAX_NEIGHBOURS + 30 : 12));
    const samples: Array<[string, number]> = [];
    for (let p = 0; p < peers; p++) {
      const id = (p === 3 ? self : (0x1000 + p * 7919).toString(16).padStart(8, '0'));
      const name = rnd() < 0.05 ? `JBL-${p}` : rnd() < 0.5 ? `NP-${id.toUpperCase()}` : `NP-${id}`;
      const n = Math.floor(rnd() * 9);
      for (let i = 0; i < n; i++) {
        const r = rnd();
        // mostly plausible RSSI incl. halves (round-half-up matters), some bogus values the phone must drop
        const rssi = r < 0.04 ? 127 : r < 0.07 ? 0 : r < 0.09 ? 5 : r < 0.11 ? -200 : Math.round((-95 + rnd() * 45) * 2) / 2;
        samples.push([name, rssi]);
      }
    }
    for (let i = samples.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [samples[i], samples[j]] = [samples[j]!, samples[i]!]; }
    const minSamples = [1, 3, 3, 5][k % 4]!;
    const c = new NeighbourCollector(self);
    for (const [name, rssi] of samples) c.add({ name, rssi });
    cases.push({ self, minSamples, max: MAX_NEIGHBOURS, samples, expected: c.neighbours(minSamples, MAX_NEIGHBOURS), peersHeard: c.peersHeard });
  }
  return { max_neighbours: MAX_NEIGHBOURS, cases };
}

class Clk implements Clock {
  constructor(public t = 0) {}
  now() { return this.t; }
  async sleep(ms: number) { this.t += ms; }
}
const keys: KeyStore = { publicKeyB64: async () => 'P', signB64: async () => 'S' };

async function retryRun(deadlineOffsetMs: number, failures: number) {
  const clock = new Clk(1_000_000);
  const times: number[] = [];
  let n = 0;
  const f = (async () => {
    times.push(clock.t - 1_000_000);
    if (n++ < failures) return { ok: false, status: 503, statusText: 'x', json: async () => ({}) } as Response;
    return { ok: true, status: 200, statusText: 'ok', json: async () => ({ status: 'accepted' }) } as Response;
  }) as unknown as typeof fetch;
  const joined = { sessionId: 'S', ephId: 'e', advertiseName: 'n', serviceUuid: 'u', advertiseUuid: 'a', discoveryEndsAtMs: 0, reportDeadlineMs: 1_000_000 + deadlineOffsetMs } as Joined;
  let delivered = true;
  try { await submitReport(new NetPresenceApi('http://x', f), keys, joined, 's', [], clock); } catch (e) { delivered = false; expect(e).toBeInstanceOf(ApiError); }
  return { deadline_offset_ms: deadlineOffsetMs, failures, attempts_at_ms: times, delivered };
}

async function retryVectors() {
  const cases = [];
  for (const d of [0, 400, 499, 500, 501, 1500, 3499, 3500, 7499, 7500, 7501, 10000, 15000, 25000]) {
    for (const failures of [1, 3, 1000]) cases.push(await retryRun(d, failures));
  }
  return { request_timeout_ms: REQUEST_TIMEOUT_MS, cases, body_bytes: bodyBytes() };
}

/** Size of the JSON body of POST /report exactly as api.ts sends it (this is what crosses the classroom Wi-Fi). */
function bodyBytes() {
  const cases = [];
  for (const n of [0, 1, 10, 40, 92, 200]) {
    const neighbours = Array.from({ length: n }, (_, i) => ({ peer_id: (0x1000 + i * 7919).toString(16).padStart(8, '0'), rssi_median: -60 - (i % 30), sample_count: 3 + (i % 40) }));
    cases.push({ n, bytes: JSON.stringify({ student_id: 'S0123456', neighbours, signature: 'A'.repeat(96) }).length });
  }
  return cases;
}

function check(file: string, value: unknown) {
  if (process.env.UPDATE_VECTORS) writeFileSync(file, JSON.stringify(value, null, 1) + '\n');
  expect(JSON.parse(readFileSync(file, 'utf-8'))).toEqual(JSON.parse(JSON.stringify(value)));
}

describe('netsim vectors', () => {
  it('collector-vectors.json is what NeighbourCollector does', () => check(FILE_C, collectorVectors()));
  it('retry-vectors.json is what submitReport does', async () => check(FILE_R, await retryVectors()));
  it('a request that never answers is aborted after REQUEST_TIMEOUT_MS and counts as transient', async () => {
    const f = ((_u: string, init: any) => new Promise((_res, rej) => init.signal.addEventListener('abort', () => rej(new Error('aborted'))))) as unknown as typeof fetch;
    const api = new NetPresenceApi('http://x', f);
    const t0 = Date.now();
    const err: any = await api.openSession().catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.transient).toBe(true);
    expect(err.message).toBe('request timed out');
    expect(Date.now() - t0).toBeGreaterThanOrEqual(REQUEST_TIMEOUT_MS - 50);
  }, 10_000);
});
