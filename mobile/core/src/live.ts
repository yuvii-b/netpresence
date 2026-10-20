/** Protocol v3: the live roll call (student and teacher phone). Platform independent; the app supplies Radio + KeyStore. */
import { ApiError, LONGPOLL_WAIT_S, type NetPresenceApi } from './api';
import { advertiseUuid } from './ble';
import { checkinMessage, loginMessage, reportMessage } from './canonical';
import type { Clock, KeyStore, LiveRow, MyStatus, Neighbour, Radio, RadioSample, TeacherLive, TeacherStart } from './types';
import { systemClock } from './types';

export const LIVE_REPORT_INTERVAL_MS = 1000;   // = backend LIVE_REPORT_INTERVAL_MS (tests/test_parity.py pins it)
export const LIVE_TICK_MS = 100;               // how often the reporter looks at the collector
export const LIVE_WINDOW = 20;                 // rolling samples kept per peer
export const LIVE_MIN_SAMPLES = 3;
export const LIVE_FIRST_NEIGHBOURS = 3;        // send the first report as soon as this many neighbours have LIVE_MIN_SAMPLES

const NAME = /^NP-([0-9a-f]{8})$/i;
const median = (xs: number[]) => {
  const s = [...xs].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m]! : Math.round((s[m - 1]! + s[m]!) / 2);
};

/** Rolling per-peer RSSI. Drops every advert whose 16-bit session tag is not ours (another class in the next room). */
export class LiveCollector {
  private readonly samples = new Map<string, number[]>();
  private lastKey = '';
  private lastEmit: number | null = null;
  private firstSampleAt: number | null = null;
  /** adverts ignored because they belong to another session */
  foreign = 0;
  constructor(private readonly selfEph: string, private readonly tag: string, private readonly opts: { minSamples?: number; window?: number } = {}) {}

  add(s: RadioSample, nowMs = Date.now()): void {
    const m = NAME.exec(s.name ?? '');
    if (!m) return;
    const peer = m[1]!.toLowerCase();
    if (peer === this.selfEph.toLowerCase()) return;
    if (!peer.startsWith(this.tag.toLowerCase())) { this.foreign++; return; }
    if (!Number.isFinite(s.rssi) || s.rssi >= 0 || s.rssi < -127) return;
    const w = this.opts.window ?? LIVE_WINDOW;
    const list = this.samples.get(peer) ?? [];
    list.push(Math.round(s.rssi));
    if (list.length > w) list.shift();
    this.samples.set(peer, list);
    this.firstSampleAt ??= nowMs;
  }

  /** Peers heard at least minSamples times, median of the last `window` samples. */
  neighbours(): Neighbour[] {
    const min = this.opts.minSamples ?? LIVE_MIN_SAMPLES;
    const out: Neighbour[] = [];
    for (const [peer, xs] of this.samples) if (xs.length >= min) out.push({ peer_id: peer, rssi_median: median(xs), sample_count: xs.length });
    return out.sort((a, b) => (a.peer_id < b.peer_id ? -1 : 1)).slice(0, 200);
  }

  get nearby(): number { return this.neighbours().length; }

  /** A report to send now, or null: only when the neighbour set or a median changed, at most every LIVE_REPORT_INTERVAL_MS;
   *  the very first one goes out as soon as 3 neighbours qualify (or after 1 s in a sparse room). */
  poll(nowMs: number, canSend = true): Neighbour[] | null {
    if (!canSend) return null;
    const nb = this.neighbours();
    if (!nb.length) return null;
    const key = JSON.stringify(nb.map((n) => [n.peer_id, n.rssi_median]));
    if (key === this.lastKey) return null;
    if (this.lastEmit === null) {
      if (nb.length < LIVE_FIRST_NEIGHBOURS && nowMs - (this.firstSampleAt ?? nowMs) < LIVE_REPORT_INTERVAL_MS) return null;
    } else if (nowMs - this.lastEmit < LIVE_REPORT_INTERVAL_MS) return null;
    this.lastKey = key;
    this.lastEmit = nowMs;
    return nb;
  }

  /** The last report did not get through: allow the same content to be sent again. */
  markUnsent(): void { this.lastKey = ''; }
}

type Api = Pick<NetPresenceApi, 'report'>;

/** Uploads incremental signed reports while `isDone()` is false. Never blocks: one request in flight, newest content wins. */
async function reportLoop(o: { api: Api; keys: KeyStore; clock: Clock; sessionId: string; reporterId: string; collector: LiveCollector;
  isDone: () => boolean; onNearby?: (n: number) => void }): Promise<void> {
  let inflight = false;
  while (!o.isDone()) {
    const nb = o.collector.poll(o.clock.now(), !inflight);
    o.onNearby?.(o.collector.nearby);
    if (nb) {
      inflight = true;
      void (async () => {
        try {
          await o.api.report(o.sessionId, o.reporterId, nb, await o.keys.signB64(reportMessage(o.sessionId, o.reporterId, nb)));
        } catch { o.collector.markUnsent(); } finally { inflight = false; }
      })();
    }
    await o.clock.sleep(LIVE_TICK_MS);
  }
}

// ======================================================================= student =======================================================================
export type StudentPhase = 'signing_in' | 'idle' | 'joining' | 'live' | 'closed' | 'not_in_class' | 'offline' | 'error';
export interface StudentState {
  phase: StudentPhase;
  subject?: { code: string; name: string };
  sessionId?: string;
  nearby: number;
  status?: 'PENDING' | 'PRESENT' | 'FLAGGED' | 'ABSENT';
  /** ms from tapping nothing (auto check-in) to the server saying PRESENT */
  timeToPresentMs?: number;
  result?: string;
  message?: string;
}

export type StudentApi = Pick<NetPresenceApi, 'health' | 'studentLogin' | 'meSession' | 'checkin' | 'report' | 'myStatus'>;
export interface StudentDeps { api: StudentApi; keys: KeyStore; radio: Radio; studentId: string; clock?: Clock; onState?: (s: StudentState) => void }

export class StudentRunner {
  private token: string | null = null;
  private stopped = false;
  private ctl = typeof AbortController !== 'undefined' ? new AbortController() : undefined;
  private readonly skip = new Set<string>();
  private readonly clock: Clock;
  state: StudentState = { phase: 'signing_in', nearby: 0 };
  constructor(private readonly d: StudentDeps) { this.clock = d.clock ?? systemClock; }

  stop() { this.stopped = true; this.ctl?.abort(); }
  private emit(p: Partial<StudentState>) { this.state = { ...this.state, ...p }; this.d.onState?.(this.state); }

  private async login(): Promise<string> {
    const attempt = async (ts: number) => this.d.api.studentLogin(this.d.studentId, ts, await this.d.keys.signB64(loginMessage(this.d.studentId, ts)));
    try {
      return (await attempt(Math.floor(this.clock.now() / 1000))).token;
    } catch (e) {
      if (!(e instanceof ApiError) || e.status !== 400) throw e;   // phone clock more than 60 s off: use the server's time
      const h = await this.d.api.health();
      return (await attempt(Math.floor(h.server_time ?? this.clock.now() / 1000))).token;
    }
  }

  /** Runs until stop(). Never sleeps between polls; network trouble shows "offline" and retries with 0.5 -> 5 s backoff. */
  async run(): Promise<void> {
    void this.d.radio.prepare?.().catch(() => undefined);
    let backoff = 500;
    while (!this.stopped) {
      try {
        if (!this.token) { this.emit({ phase: 'signing_in', message: undefined }); this.token = await this.login(); }
        const polled = this.clock.now();
        const s = await this.d.api.meSession(this.token, LONGPOLL_WAIT_S, this.ctl?.signal);
        backoff = 500;
        if (s.status !== 'open' && this.clock.now() - polled < 1000) await this.clock.sleep(1000 - (this.clock.now() - polled)); // a proxy that ignores long-poll must not make us spin
        if (s.session_id && this.skip.has(s.session_id)) { await this.clock.sleep(3000); continue; }   // keep showing why
        if (s.status !== 'open' || !s.session_id) {
          this.emit({ phase: 'idle', message: undefined, sessionId: undefined, status: undefined, nearby: 0, timeToPresentMs: undefined });
          continue;
        }
        await this.rollCall(s as Required<Pick<typeof s, 'session_id' | 'nonce'>> & typeof s);
      } catch (e) {
        if (this.stopped) return;
        if (e instanceof ApiError && e.status === 401) { this.token = null; continue; }
        if (e instanceof ApiError && e.transient) {
          this.emit({ phase: 'offline', message: 'Cannot reach the server. Check the Wi-Fi - trying again.' });
          await this.clock.sleep(backoff);
          backoff = Math.min(backoff * 2, 5000);
          continue;
        }
        this.emit({ phase: 'error', message: e instanceof Error ? e.message : 'Something went wrong.' });
        await this.clock.sleep(3000);
      }
    }
  }

  private async rollCall(s: { session_id: string; nonce?: string; tag?: string; subject?: { code: string; name: string } }) {
    const t0 = this.clock.now();
    const sid = s.session_id;
    this.emit({ phase: 'joining', sessionId: sid, subject: s.subject && { code: s.subject.code, name: s.subject.name }, status: 'PENDING', nearby: 0 });
    let res;
    try {
      res = await this.d.api.checkin(sid, this.d.studentId, await this.d.keys.signB64(checkinMessage(sid, s.nonce ?? '')));
    } catch (e) {
      if (e instanceof ApiError && (e.status === 403 || e.status === 400)) {   // not on the roster / roll call already over
        this.skip.add(sid);
        this.emit({ phase: e.status === 403 ? 'not_in_class' : 'idle', message: e.message });
        return;
      }
      throw e;
    }
    const collector = new LiveCollector(res.eph_id, (res as { tag?: string }).tag ?? s.tag ?? res.eph_id.slice(0, 4));
    await this.d.radio.start(res.advertise_name, res.advertise_uuid ?? advertiseUuid(res.eph_id), (smp) => collector.add(smp, this.clock.now()));
    this.emit({ phase: 'live' });
    let done = false;
    const token = this.token!;
    const status = async () => {
      let since = 0;
      while (!done && !this.stopped) {
        let r: MyStatus;
        try { r = await this.d.api.myStatus(token, sid, since, LONGPOLL_WAIT_S, this.ctl?.signal); }
        catch (e) {
          if (this.stopped) return;
          if (e instanceof ApiError && e.status === 401) { this.token = null; done = true; return; }
          if (e instanceof ApiError && e.transient) { this.emit({ message: 'Connection lost - retrying.' }); await this.clock.sleep(500); continue; }
          throw e;
        }
        since = r.rev;
        if (r.status === 'CLOSED') { done = true; this.emit({ phase: 'closed', result: r.result ?? undefined, message: undefined }); return; }
        if (r.status !== 'NONE') {
          const first = r.status === 'PRESENT' && this.state.status !== 'PRESENT';
          this.emit({ status: r.status, message: undefined, ...(first ? { timeToPresentMs: this.clock.now() - t0 } : {}) });
        }
      }
    };
    try {
      await Promise.all([
        reportLoop({ api: this.d.api, keys: this.d.keys, clock: this.clock, sessionId: sid, reporterId: this.d.studentId, collector,
          isDone: () => done || this.stopped, onNearby: (n) => { if (n !== this.state.nearby) this.emit({ nearby: n }); } }),
        status().finally(() => { done = true; }),
      ]);
    } finally {
      await this.d.radio.stop().catch(() => undefined);
    }
  }
}

// ======================================================================= teacher =======================================================================
export type TeacherApi = Pick<NetPresenceApi, 'startSubject' | 'teacherLive' | 'teacherFinish' | 'teacherAdjudicate' | 'report'>;
export interface TeacherDeps {
  api: TeacherApi; keys: KeyStore; radio: Radio; token: string; model: string; clock?: Clock;
  onLive?: (l: TeacherLive) => void; onError?: (message: string, offline: boolean) => void;
}

/** The teacher phone: the seed. It advertises and scans like a student phone and watches the class fill up. */
export class TeacherRoll {
  private done = false;
  private ctl = typeof AbortController !== 'undefined' ? new AbortController() : undefined;
  private readonly clock: Clock;
  start!: TeacherStart;
  last: TeacherLive | null = null;
  constructor(private readonly d: TeacherDeps) { this.clock = d.clock ?? systemClock; }

  async begin(subjectId: string): Promise<TeacherStart> {
    void this.d.radio.prepare?.().catch(() => undefined);
    this.start = await this.d.api.startSubject(this.d.token, subjectId, { public_key: await this.d.keys.publicKeyB64(), model: this.d.model });
    const collector = new LiveCollector(this.start.teacher_eph, this.start.tag);
    await this.d.radio.start(this.start.advertise_name, this.start.advertise_uuid, (s) => collector.add(s, this.clock.now()));
    void reportLoop({ api: this.d.api, keys: this.d.keys, clock: this.clock, sessionId: this.start.session_id,
      reporterId: this.start.teacher_student_id, collector, isDone: () => this.done }).finally(() => this.d.radio.stop().catch(() => undefined));
    void this.watch();
    return this.start;
  }

  private async watch() {
    let since = -1;
    let backoff = 500;
    while (!this.done) {
      try {
        const l = await this.d.api.teacherLive(this.d.token, this.start.session_id, since, LONGPOLL_WAIT_S, this.ctl?.signal);
        backoff = 500;
        since = l.rev;
        this.last = l;
        this.d.onLive?.(l);
        if (l.status === 'closed') { this.done = true; return; }
      } catch (e) {
        if (this.done) return;
        const transient = e instanceof ApiError && e.transient;
        this.d.onError?.(transient ? 'Cannot reach the server - trying again.' : e instanceof Error ? e.message : 'Something went wrong.', transient);
        await this.clock.sleep(backoff);
        backoff = Math.min(backoff * 2, 5000);
      }
    }
  }

  adjudicate(studentId: string, status: 'PRESENT' | 'ABSENT') {
    return this.d.api.teacherAdjudicate(this.d.token, this.start.session_id, studentId, status);
  }

  async finish() {
    const out = await this.d.api.teacherFinish(this.d.token, this.start.session_id);
    this.done = true;
    this.ctl?.abort();
    return out;
  }
}

export type { LiveRow };

/** CSV of a finished roll call (RFC 4180 quoting). */
export function attendanceCsv(subjectCode: string, rows: Array<{ student_id: string; name: string; status: string }>): string {
  const q = (v: string) => (/[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);
  return ['student_id,name,status,subject', ...rows.map((r) => [r.student_id, r.name, r.status, subjectCode].map(q).join(','))].join('\n') + '\n';
}
