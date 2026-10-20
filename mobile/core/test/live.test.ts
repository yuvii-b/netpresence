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
import { StudentRunner, TeacherRoll, type StudentState } from '../src/live';
import { NodeKeyStore, ReplayRadio } from '../src/node';
import type { Clock, Joined, Radio, RadioSample } from '../src/types';

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

  it('live flow (protocol v3): 93 students + a teacher phone seed, auto check-in, Present pushed within seconds', async () => {
    const fx = JSON.parse(readFileSync(path.resolve(__dirname, 'fixtures/scene93.json'), 'utf8'));
    const api = new NetPresenceApi(BASE);
    const P = 'live93.';
    const sid = (id: string) => P + id;
    const ids: string[] = Object.keys(fx.people).map(sid);
    const person = (id: string) => fx.people[id.slice(P.length)];
    const keys = new Map(ids.map((id) => [id, new NodeKeyStore()]));
    await api.teacher.addTeacher(TOKEN, 'Dr Live', 'LIVE-CODE');
    await api.teacher.addSubject(TOKEN, 'LIVE-CODE', 'LV93', 'Live 93', ids);
    await chunks(ids, 20, (id) => enroll(api, keys.get(id)!, { studentId: id, name: id, model: person(id).model }));
    for (const [model, off] of Object.entries<number>(fx.calibration_offsets)) await api.teacher.setCalibration(TOKEN, model, off);
    const login = await api.teacherLogin('LIVE-CODE');
    expect(login.subjects.map((s) => s.code)).toEqual(['LV93']);

    // Fake radio: every 100 ms (the Android advert interval) a phone "hears" each peer it heard in the scene (replaying the
    // scene's RSSI series). A phone's own ephemeral id is learned from the advertise name the app hands to radio.start().
    const ephOf = new Map<string, string>();
    class SceneRadio implements Radio {
      private timer?: ReturnType<typeof setInterval>;
      private k = 0;
      constructor(private readonly self: string, private readonly heard: Record<string, number[]>) {}
      async start(name: string, _u: string, cb: (s: RadioSample) => void) {
        ephOf.set(this.self, name.slice(3));
        this.timer = setInterval(() => {
          this.k++;
          for (const [peer, rs] of Object.entries(this.heard)) {
            const eph = ephOf.get(peer);
            if (eph) cb({ name: `NP-${eph}`, rssi: rs[this.k % rs.length]! });
          }
        }, 100);
      }
      async stop() { clearInterval(this.timer); }
    }
    const teacherKey = 'TEACHER';
    const jitter = [-63, -64, -65, -64, -63];   // the teacher's phone sits ~1.5 m in front of the seeds, both ways
    const seeds: string[] = fx.seeds.map(sid);
    const heardBy = (id: string) => {
      const h: Record<string, number[]> = {};
      for (const [peer, rs] of Object.entries<number[]>(person(id).samples)) h[sid(peer)] = rs;
      if (seeds.includes(id)) h[teacherKey] = jitter;
      return h;
    };
    const tPresent = new Map<string, number>();
    let tStart = 0;
    const runners = ids.map((id) => {
      const r = new StudentRunner({ api, keys: keys.get(id)!, radio: new SceneRadio(id, heardBy(id)), studentId: id,
        onState: (s: StudentState) => { if (s.status === 'PRESENT' && !tPresent.has(id)) tPresent.set(id, performance.now() - tStart); } });
      return { r, run: r.run() };
    });
    await new Promise((r) => setTimeout(r, 2000));      // everybody has the app open and is long-polling

    const teacher = new TeacherRoll({ api, keys: new NodeKeyStore(), model: 'ref', token: login.token,
      radio: new SceneRadio(teacherKey, Object.fromEntries(seeds.map((s) => [s, jitter]))) });
    tStart = performance.now();
    const st = await teacher.begin(login.subjects[0]!.subject_id);
    expect(st.tag).toMatch(/^[0-9a-f]{4}$/);
    const expected = new Set<string>(fx.expected_present.map(sid));
    const deadline = Date.now() + 40_000;
    while (Date.now() < deadline && [...expected].some((i) => !tPresent.has(i))) await new Promise((r) => setTimeout(r, 50));

    const lat = [...expected].map((i) => tPresent.get(i) ?? Infinity).sort((a, b) => a - b);
    const q = (p: number) => lat[Math.min(lat.length - 1, Math.ceil(p * lat.length) - 1)]!;
    console.log(`live93 time-to-present from teacher Start (fake radio, real server, one machine): p50=${q(0.5).toFixed(0)} ms p95=${q(0.95).toFixed(0)} ms max=${lat[lat.length - 1]!.toFixed(0)} ms`);
    const out = await teacher.finish();
    runners.forEach(({ r }) => r.stop());
    await Promise.all(runners.map(({ run }) => run));
    const present = out.rows.filter((r) => r.status === 'PRESENT').map((r) => r.student_id).sort();
    expect(present).toEqual([...expected].sort());                                  // same verdict as the engine on this scene
    expect(ids.filter((i) => person(i).remote && present.includes(i))).toEqual([]); // remote cheaters never admitted
    expect(lat[lat.length - 1]).toBeLessThan(Infinity);                             // every in-room phone saw PRESENT before the finish
    expect(q(0.95)).toBeLessThanOrEqual(5000);                                      // pre-declared: p95 <= 5 s
  }, 120_000);
});
