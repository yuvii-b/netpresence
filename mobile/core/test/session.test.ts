import { describe, expect, it } from 'vitest';
import { ApiError, NetPresenceApi } from '../src/api';
import { checkinMessage, reportMessage } from '../src/canonical';
import { discover, joinSession, markPresent, NoOpenSession, submitReport } from '../src/session';
import { advertiseUuid } from '../src/ble';
import type { Clock, Joined, KeyStore } from '../src/types';
import { ReplayRadio } from '../src/node';

class VirtualClock implements Clock {
  constructor(public t = 1_000_000_000_000) {}
  now() { return this.t; }
  async sleep(ms: number) { this.t += ms; }
}
const keys: KeyStore = { publicKeyB64: async () => 'PUB', signB64: async (m) => `sig(${m})` };

function fakeFetch(handlers: Array<(url: string, init: any) => { status: number; body: unknown }>) {
  const calls: Array<{ url: string; body: any }> = [];
  const f = (async (url: string, init: any) => {
    const h = handlers[Math.min(calls.length, handlers.length - 1)]!;
    calls.push({ url, body: init?.body ? JSON.parse(init.body) : undefined });
    const r = h(url, init);
    return { ok: r.status < 400, status: r.status, statusText: 'x', json: async () => r.body } as Response;
  }) as unknown as typeof fetch;
  return { f, calls };
}

describe('joinSession', () => {
  it('signs the server nonce and corrects for a phone clock that is 20 s fast', async () => {
    const clock = new VirtualClock(1_000_000_000_000); // phone thinks it is T
    const serverNow = (clock.t - 20_000) / 1000; // server is 20 s behind the phone
    const { f, calls } = fakeFetch([
      () => ({ status: 200, body: { status: 'open', session_id: 'S-1', nonce: 'N1' } }),
      () => ({ status: 200, body: { eph_id: 'deadbeef', advertise_name: 'NP-deadbeef', service_uuid: 'U', window_ends_at: serverNow + 40, discovery_ends_at: serverNow + 45, report_deadline: serverNow + 60, server_time: serverNow } }),
    ]);
    const j = await joinSession(new NetPresenceApi('http://x', f), keys, 'stu', clock);
    expect(calls[1]!.body.signature).toBe(`sig(${checkinMessage('S-1', 'N1')})`);
    expect(j.discoveryEndsAtMs - clock.t).toBeCloseTo(45_000, -1); // discovery runs to the TAIL (45 s), not check-in close (40 s), in PHONE time
    expect(j.advertiseUuid).toBe('6e657470-7265-7365-6e63-6500deadbeef');  // derived when an older server omits it
    expect(j.reportDeadlineMs - clock.t).toBeCloseTo(60_000, -1);
  });
  it('throws NoOpenSession when nothing is running', async () => {
    const { f } = fakeFetch([() => ({ status: 200, body: { status: 'none' } })]);
    await expect(joinSession(new NetPresenceApi('http://x', f), keys, 'stu')).rejects.toBeInstanceOf(NoOpenSession);
  });
});

const joined = (clock: Clock): Joined => ({ sessionId: 'S-1', ephId: 'aaaaaaaa', advertiseName: 'NP-aaaaaaaa', serviceUuid: 'U',
  advertiseUuid: advertiseUuid('aaaaaaaa'),
  discoveryEndsAtMs: clock.now() + 10_000, reportDeadlineMs: clock.now() + 25_000 });

describe('discover', () => {
  it('advertises our name, listens until the window ends, stops the radio', async () => {
    const clock = new VirtualClock();
    const radio = new ReplayRadio([1, 2, 3, 4].map(() => ({ name: 'NP-0a1b2c3d', rssi: -61 })));
    const r = await discover(radio, joined(clock), clock);
    expect(radio.started).toEqual({ name: 'NP-aaaaaaaa', uuid: '6e657470-7265-7365-6e63-6500aaaaaaaa' });   // identity in the UUID
    expect(radio.stopped).toBe(1);
    expect(r.neighbours).toEqual([{ peer_id: '0a1b2c3d', rssi_median: -61, sample_count: 4 }]);
    expect(r.discoveryMs).toBeGreaterThanOrEqual(10_000);
  });
  it('stops the radio even if the wait blows up', async () => {
    const clock = new VirtualClock();
    clock.sleep = async () => { throw new Error('app killed'); };
    const radio = new ReplayRadio([]);
    await expect(discover(radio, joined(clock), clock)).rejects.toThrow('app killed');
    expect(radio.stopped).toBe(1);
  });
});

describe('submitReport', () => {
  const nb = [{ peer_id: '0a1b2c3d', rssi_median: -61, sample_count: 4 }];
  it('signs the canonical report and retries transient failures with back-off', async () => {
    const clock = new VirtualClock();
    const { f, calls } = fakeFetch([
      () => ({ status: 503, body: { detail: 'down' } }),
      () => ({ status: 503, body: {} }),
      () => ({ status: 200, body: { status: 'accepted', neighbours: 1 } }),
    ]);
    const r = await submitReport(new NetPresenceApi('http://x', f), keys, joined(clock), 'stu', nb, clock);
    expect(r.attempts).toBe(3);
    expect(calls[2]!.body.signature).toBe(`sig(${reportMessage('S-1', 'stu', nb)})`);
    expect(clock.t - 1_000_000_000_000).toBe(500 + 1000); // back-off 0.5 s then 1 s
  });
  it('does not retry a 4xx (bad signature / closed window)', async () => {
    const clock = new VirtualClock();
    const { f, calls } = fakeFetch([() => ({ status: 401, body: { detail: 'Bad signature.' } })]);
    await expect(submitReport(new NetPresenceApi('http://x', f), keys, joined(clock), 'stu', nb, clock)).rejects.toMatchObject({ status: 401 });
    expect(calls).toHaveLength(1);
  });
  it('gives up at the report deadline instead of retrying forever', async () => {
    const clock = new VirtualClock();
    const { f, calls } = fakeFetch([() => ({ status: 503, body: {} })]);
    await expect(submitReport(new NetPresenceApi('http://x', f), keys, joined(clock), 'stu', nb, clock)).rejects.toBeInstanceOf(ApiError);
    expect(clock.t).toBeLessThanOrEqual(1_000_000_000_000 + 25_000);
    expect(calls.length).toBeGreaterThan(3);
  });
  it('treats a network failure as transient', async () => {
    const clock = new VirtualClock();
    let n = 0;
    const f = (async () => { if (n++ < 2) throw new TypeError('Network request failed'); return { ok: true, status: 200, json: async () => ({ status: 'accepted' }) } as Response; }) as unknown as typeof fetch;
    expect((await submitReport(new NetPresenceApi('http://x', f), keys, joined(clock), 'stu', nb, clock)).attempts).toBe(3);
  });
});

describe('markPresent (whole flow)', () => {
  it('open -> check in -> discover -> report', async () => {
    const clock = new VirtualClock();
    const now = clock.t / 1000;
    const { f, calls } = fakeFetch([
      () => ({ status: 200, body: { status: 'open', session_id: 'S-9', nonce: 'N' } }),
      () => ({ status: 200, body: { eph_id: 'cafef00d', advertise_name: 'NP-cafef00d', service_uuid: 'U', window_ends_at: now + 20, report_deadline: now + 35, server_time: now } }),
      () => ({ status: 200, body: { status: 'accepted', neighbours: 1 } }),
    ]);
    const radio = new ReplayRadio([-60, -62, -64].map((rssi) => ({ name: 'NP-0a1b2c3d', rssi })));
    const r = await markPresent({ api: new NetPresenceApi('http://x', f), keys, radio, studentId: 'stu', clock });
    expect(calls.map((c) => c.url.replace('http://x', ''))).toEqual(['/api/sessions/open', '/api/sessions/S-9/checkin', '/api/sessions/S-9/report']);
    expect(r.neighbours).toEqual([{ peer_id: '0a1b2c3d', rssi_median: -62, sample_count: 3 }]);
  });
});
