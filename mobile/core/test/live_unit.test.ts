import { describe, expect, it } from 'vitest';
import { ApiError } from '../src/api';
import { attendanceCsv, sheetCsv, DiagBoard, LIVE_WINDOW, LiveCollector, StudentRunner, TeacherRoll, type StudentState } from '../src/live';
import type { KeyStore, Radio, RadioSample } from '../src/types';

const TAG = 'ab12';
const nm = (member: string) => `NP-${TAG}${member}`;

describe('LiveCollector', () => {
  it('drops adverts of another session (tag filter) and of itself', () => {
    const c = new LiveCollector(`${TAG}0001`, TAG);
    for (let i = 0; i < 5; i++) {
      c.add({ name: nm('0002'), rssi: -60 });
      c.add({ name: 'NP-ffff0002', rssi: -50 });   // next room's class
      c.add({ name: nm('0001'), rssi: -40 });      // myself
    }
    expect(c.neighbours().map((n) => n.peer_id)).toEqual([`${TAG}0002`]);
    expect(c.foreign).toBe(5);
  });

  it('uses the median of the last LIVE_WINDOW samples and needs 3 samples', () => {
    const c = new LiveCollector(`${TAG}0001`, TAG);
    c.add({ name: nm('0002'), rssi: -60 }); c.add({ name: nm('0002'), rssi: -61 });
    expect(c.neighbours()).toEqual([]);
    c.add({ name: nm('0002'), rssi: -80 });
    expect(c.neighbours()[0]).toMatchObject({ rssi_median: -61, sample_count: 3 });
    for (let i = 0; i < LIVE_WINDOW + 10; i++) c.add({ name: nm('0002'), rssi: -70 });   // old samples roll out
    expect(c.neighbours()[0]).toMatchObject({ rssi_median: -70, sample_count: LIVE_WINDOW });
  });

  it('sends the first report as soon as 3 neighbours qualify, then at most once a second and only on change', () => {
    const c = new LiveCollector(`${TAG}0001`, TAG);
    const feed = (m: string, rssi: number, n = 3) => { for (let i = 0; i < n; i++) c.add({ name: nm(m), rssi }, 0); };
    feed('0002', -60); feed('0003', -62);
    expect(c.poll(100)).toBeNull();                 // only 2 neighbours, < 1 s since the first sample: wait
    feed('0004', -64);
    const first = c.poll(120)!;
    expect(first).toHaveLength(3);                  // ASAP at 120 ms
    expect(c.poll(500)).toBeNull();                 // unchanged
    feed('0002', -50, 12);                          // median moved
    expect(c.poll(900)).toBeNull();                 // changed but < 1 s since the last report
    expect(c.poll(1200)).not.toBeNull();
    expect(c.poll(2500)).toBeNull();
    c.markUnsent();
    expect(c.poll(2600)).not.toBeNull();            // a failed upload is retried with the same content
  });

  it('a sparse room (1 neighbour) reports after 1 s', () => {
    const c = new LiveCollector(`${TAG}0001`, TAG);
    for (let i = 0; i < 3; i++) c.add({ name: nm('0002'), rssi: -60 }, 0);
    expect(c.poll(500)).toBeNull();
    expect(c.poll(1000)).toHaveLength(1);
  });
});

const keys: KeyStore = { publicKeyB64: async () => 'PUB', signB64: async (m) => `sig(${m})` };
class FakeRadio implements Radio {
  started = 0; stopped = 0; prepared = 0; cb?: (s: RadioSample) => void;
  async prepare() { this.prepared++; }
  async start(_n: string, _u: string, cb: (s: RadioSample) => void) { this.started++; this.cb = cb; }
  async stop() { this.stopped++; }
}
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
const until = async (f: () => boolean, ms = 4000) => { const t = Date.now(); while (!f()) { if (Date.now() - t > ms) throw new Error('timeout'); await wait(10); } };

function studentApi(over: Record<string, any> = {}) {
  const calls: Record<string, any[]> = { report: [], checkin: [], login: [] };
  let polls = 0, statuses = 0;
  const api: any = {
    health: async () => ({ status: 'ok', server_time: 1_900_000_000 }),
    studentLogin: async (...a: any[]) => { calls.login!.push(a); return { token: 'TOK', name: 'n' }; },
    meSession: async () => { polls++; if (polls === 1) return { status: 'none' }; return { status: 'open', session_id: 'S-1', nonce: 'N', tag: TAG, subject: { code: 'CS301', name: 'OS' } }; },
    checkin: async (sid: string, id: string, sig: string) => { calls.checkin!.push([sid, id, sig]); return { eph_id: `${TAG}0007`, advertise_name: `NP-${TAG}0007`, advertise_uuid: `u${TAG}0007`, tag: TAG }; },
    report: async (sid: string, id: string, nb: any[], sig: string) => { calls.report!.push({ sid, id, nb, sig }); return { status: 'accepted' }; },
    myStatus: async () => { statuses++; await wait(120); return statuses === 1 ? { rev: 1, status: 'PENDING', at: 0 } : statuses === 2 ? { rev: 2, status: 'PRESENT', at: 1 } : { rev: 3, status: 'CLOSED', at: 2, result: 'PRESENT' }; },
    ...over,
  };
  return { api, calls };
}

describe('StudentRunner diagnostics', () => {
  it('tells the person what is happening and keeps the finished result on screen', async () => {
    let polls = 0, tick = 0;
    const { api } = studentApi({ meSession: async () => { polls++; return polls === 2 ? { status: 'open', session_id: 'S-1', nonce: 'N', tag: TAG, subject: { code: 'CS301', name: 'OS' } } : { status: 'none' }; } });
    const radio = new FakeRadio();
    const board = new DiagBoard(undefined, () => (tick += 300));   // every call is 300 ms later: the 250 ms throttle never skips
    const r = new StudentRunner({ api, keys, radio, studentId: 'stu', diag: board });
    const run = r.run();
    await until(() => radio.started === 1);
    for (const m of ['0002', '0003', '0004']) for (let i = 0; i < 3; i++) radio.cb!({ name: nm(m), rssi: -60 });
    await until(() => r.state.phase === 'closed');
    await wait(1300);                                      // another poll finds no open class: the result must stay
    expect(r.state.phase).toBe('closed');
    r.stop(); await run;
    const text = board.state.log.join('\n');
    for (const needle of ['signed in', 'class started: CS301', 'broadcasting as', 'Bluetooth on', 'first report sent', 'server says: PRESENT', 'Bluetooth off'])
      expect(text).toContain(needle);
    expect(board.state.radio).toBe('off');
    expect(board.state.sent).toBeGreaterThanOrEqual(1);
    expect(board.state.peers).toHaveLength(3);
    expect(board.state.adverts).toBe(9);
  });
});

describe('StudentRunner', () => {
  it('auto check-in, radio on, reports, Present, closed - without any tap', async () => {
    const { api, calls } = studentApi();
    const radio = new FakeRadio();
    const states: StudentState[] = [];
    const r = new StudentRunner({ api, keys, radio, studentId: 'stu', onState: (s) => states.push({ ...s }) });
    const run = r.run();
    await until(() => radio.started === 1);
    for (const m of ['0002', '0003', '0004']) for (let i = 0; i < 3; i++) radio.cb!({ name: nm(m), rssi: -60 });
    await until(() => r.state.phase === 'closed');
    r.stop(); await run;
    expect(radio.prepared).toBe(1);
    expect(radio.stopped).toBe(1);
    expect(calls.checkin![0]![2]).toBe('sig(checkin:S-1:N)');
    expect(calls.report!.length).toBeGreaterThanOrEqual(1);
    expect(calls.report![0].nb).toHaveLength(3);
    expect(calls.report![0].sig).toBe(`sig(report:S-1:stu:${JSON.stringify(calls.report![0].nb.map((n: any) => [n.peer_id, n.rssi_median, n.sample_count]))})`);
    expect(states.map((s) => s.phase)).toEqual(expect.arrayContaining(['signing_in', 'idle', 'joining', 'live', 'closed']));
    expect(states.find((s) => s.status === 'PRESENT')?.timeToPresentMs).toBeGreaterThan(0);
    expect(r.state.result).toBe('PRESENT');
  });

  it('not on the roster: 403 -> red state with the server message, radio never starts', async () => {
    const { api } = studentApi({ checkin: async () => { throw new ApiError(403, 'You are not in CS301.'); } });
    const radio = new FakeRadio();
    const r = new StudentRunner({ api, keys, radio, studentId: 'stu' });
    const run = r.run();
    await until(() => r.state.phase === 'not_in_class');
    r.stop(); await run;
    expect(r.state.message).toBe('You are not in CS301.');
    expect(radio.started).toBe(0);
  });

  it('network down -> offline with a plain message, then recovers by itself', async () => {
    let n = 0;
    const { api } = studentApi({ meSession: async () => { n++; if (n <= 2) throw new ApiError(0, 'Network request failed'); return { status: 'none' }; } });
    const seen: string[] = [];
    const r = new StudentRunner({ api, keys, radio: new FakeRadio(), studentId: 'stu', onState: (s) => seen.push(s.phase) });
    const run = r.run();
    await until(() => n >= 3);
    await until(() => r.state.phase === 'idle');
    r.stop(); await run;
    expect(seen).toContain('offline');
  });

  it('phone clock off by minutes: login retries with the server time', async () => {
    let first = true;
    const { api, calls } = studentApi({ studentLogin: async (...a: any[]) => { calls.login!.push(a); if (first) { first = false; throw new ApiError(400, 'clock'); } return { token: 'T' }; } });
    const r = new StudentRunner({ api, keys, radio: new FakeRadio(), studentId: 'stu' });
    const run = r.run();
    await until(() => calls.login!.length === 2);
    r.stop(); await run;
    expect(calls.login![1]![1]).toBe(1_900_000_000);
  });
});

describe('TeacherRoll', () => {
  it('starts the subject, advertises as the seed, reports as the teacher id, long-polls and finishes', async () => {
    const reports: any[] = [];
    let live = 0;
    const api: any = {
      startSubject: async () => ({ session_id: 'S-9', nonce: 'N', tag: TAG, teacher_student_id: 'TEACHER.T-1', teacher_eph: `${TAG}0000`, advertise_name: `NP-${TAG}0000`, advertise_uuid: `u${TAG}0000`, server_time: 0, live_ends_at: 0, subject: { subject_id: 'x', code: 'CS301', name: 'OS', roster_size: 3 } }),
      teacherLive: async () => { live++; await wait(50); return { rev: live, status: live > 2 ? 'closed' : 'open', counts: { PRESENT: live }, rows: [], stable_for_s: 0, elapsed_s: 1, roster_size: 3 }; },
      teacherFinish: async () => ({ counts: { PRESENT: 3 }, rows: [] }),
      teacherAdjudicate: async () => ({}),
      report: async (sid: string, id: string, nb: any[]) => { reports.push({ sid, id, nb }); return {}; },
    };
    const radio = new FakeRadio();
    const seen: number[] = [];
    const t = new TeacherRoll({ api, keys, radio, token: 'TT', model: 'Pixel', onLive: (l) => seen.push(l.rev) });
    await t.begin('x');
    for (const m of ['0002', '0003', '0004']) for (let i = 0; i < 3; i++) radio.cb!({ name: nm(m), rssi: -61 });
    await until(() => reports.length >= 1);
    expect(reports[0].id).toBe('TEACHER.T-1');
    await until(() => seen.length >= 3);
    expect((await t.finish()).counts.PRESENT).toBe(3);
    await until(() => radio.stopped === 1);
  });
});

describe('attendanceCsv', () => {
  it('quotes commas and quotes', () => {
    expect(attendanceCsv('CS301', [{ student_id: '1', name: 'Rao, A "Ace"', status: 'PRESENT' }])).toBe('student_id,name,status,subject\n1,"Rao, A ""Ace""",PRESENT,CS301\n');
  });
});

describe('sheetCsv', () => {
  it('one row per student, one column per class, quoting names with commas', () => {
    const csv = sheetCsv({
      subject: { subject_id: 'x', code: 'CS301', name: 'OS' },
      sessions: [{ session_id: 'S-aaaaaa', at: 1_900_000_000, present: 1, total: 2 }, { session_id: 'S-bbbbbb', at: null, present: 2, total: 2 }],
      students: [{ student_id: '21CT001', name: 'Rao, A', marks: ['P', 'P'], present: 2, pct: 100 }, { student_id: '21CT002', name: 'B', marks: ['A', '-'], present: 0, pct: 0 }],
    });
    const lines = csv.trim().split('\n');
    expect(lines[0]).toBe('student_id,name,2030-03-17 17:46,bbbbbb,present,held,percent');
    expect(lines[1]).toBe('21CT001,"Rao, A",P,P,2,2,100');
    expect(lines[2]).toBe('21CT002,B,A,-,0,1,0');
  });
});
