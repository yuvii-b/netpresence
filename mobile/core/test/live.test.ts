/**
 * Cross-language end-to-end: REAL mobile-core code (TypeScript, Node P-256 keys) as 100+ phones
 * against the REAL Python server process (in-memory DB). Run: NP_PYTHON=/path/to/python npm run test:live
 */
import { ChildProcess, spawn } from 'node:child_process';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { NetPresenceApi } from '../src/api';
import { discover, enroll, joinSession, submitReport } from '../src/session';
import { NodeKeyStore, ReplayRadio } from '../src/node';
import type { Clock, Joined } from '../src/types';

const PY = process.env.NP_PYTHON;
const PORT = 18000 + Math.floor(Math.random() * 1000);
const BASE = `http://127.0.0.1:${PORT}`;
const TOKEN = 'live-test-token';
let server: ChildProcess;

async function waitUp() {
  for (let i = 0; i < 100; i++) {
    try { if ((await fetch(`${BASE}/api/health`)).ok) return; } catch { /* not yet */ }
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error('server did not start');
}
const chunks = async <T>(xs: T[], n: number, fn: (x: T) => Promise<unknown>) => { for (let i = 0; i < xs.length; i += n) await Promise.all(xs.slice(i, i + n).map(fn)); };

describe.skipIf(!PY)('mobile core <-> live server', () => {
  beforeAll(async () => {
    server = spawn(PY!, ['-m', 'tools.dev_server', '--port', String(PORT), '--token', TOKEN], {
      cwd: path.resolve(__dirname, '../../../backend'), stdio: 'ignore' });
    await waitUp();
  }, 60_000);
  afterAll(() => { server?.kill(); });

  for (const name of ['scene93', 'scene35']) {
    it(`${name}: every phone runs the real flow; the server's verdict equals the graph engine's`, async () => {
      const fx = JSON.parse(readFileSync(path.resolve(__dirname, `fixtures/${name}.json`), 'utf8'));
      const api = new NetPresenceApi(BASE);
      const raw: string[] = Object.keys(fx.people);
      const sid = (id: string) => `${name}.${id}`;           // both scenes share one server: keep student ids distinct
      const ids = raw.map(sid);
      const person = (id: string) => fx.people[id.slice(name.length + 1)];
      const phones = new Map(ids.map((id) => [id, new NodeKeyStore()]));

      await chunks(ids, 20, (id) => enroll(api, phones.get(id)!, { studentId: id, name: id, model: person(id).model }));
      for (const [model, off] of Object.entries<number>(fx.calibration_offsets)) await api.teacher.setCalibration(TOKEN, model, off);
      await api.teacher.startSession(TOKEN, {});

      const joined = new Map<string, Joined>();
      await chunks(ids, 15, async (id) => { joined.set(id, await joinSession(api, phones.get(id)!, id)); });
      expect(new Set([...joined.values()].map((j) => j.ephId)).size).toBe(ids.length); // ephemeral ids are unique

      // discovery runs on a virtual clock so the 45 s window costs no wall time; the server still sees real time
      const vclock: Clock = (() => { let t = Date.now(); return { now: () => t, sleep: async (ms: number) => { t += ms; } }; })();
      let reported = 0;
      await chunks(ids, 15, async (id) => {
        const samples = Object.entries<number[]>(person(id).samples).flatMap(([peer, rs]) =>
          rs.map((rssi) => ({ name: `NP-${joined.get(sid(peer))!.ephId}`, rssi })));
        const j = joined.get(id)!;
        const found = await discover(new ReplayRadio(samples), j, vclock);
        await submitReport(api, phones.get(id)!, j, id, found.neighbours, vclock);
        reported++;
      });
      expect(reported).toBe(ids.length);

      const session = [...joined.values()][0]!.sessionId;
      await api.teacher.verifySeeds(TOKEN, session, fx.seeds.map(sid));
      const out = await api.teacher.close(TOKEN, session);
      const roster = new Set(ids);
      const present = out.rows.filter((r) => r.status === 'PRESENT' && roster.has(r.student_id)).map((r) => r.student_id).sort();
      expect(present).toEqual(fx.expected_present.map(sid).sort());
      const away = ids.filter((i) => person(i).remote);
      expect(away.length).toBeGreaterThan(0);
      expect(away.filter((a) => present.includes(a))).toEqual([]); // remote cheaters never admitted
    }, 180_000);
  }
});
