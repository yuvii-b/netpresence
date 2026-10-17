import { NeighbourCollector } from './aggregate';
import { advertiseUuid } from './ble';
import { ApiError, NetPresenceApi } from './api';
import { checkinMessage, registerMessage, reportMessage } from './canonical';
import type { Clock, Joined, KeyStore, Neighbour, Radio } from './types';
import { systemClock } from './types';

/** One-time enrolment: binds this phone's hardware key to the student id. */
export async function enroll(api: NetPresenceApi, keys: KeyStore, who: { studentId: string; name: string; model: string; enrolCode?: string }) {
  return api.register({
    student_id: who.studentId, name: who.name, model: who.model,
    public_key: await keys.publicKeyB64(),
    signature: await keys.signB64(registerMessage(who.studentId, who.model)),
    ...(who.enrolCode ? { enrol_code: who.enrolCode } : {}),
  });
}

export class NoOpenSession extends Error {
  constructor() {
    super('No roll call is open right now.');
  }
}

/** Find the open roll call and check in. Phone-clock skew is measured against the server's clock. */
export async function joinSession(api: NetPresenceApi, keys: KeyStore, studentId: string, clock: Clock = systemClock): Promise<Joined> {
  const open = await api.openSession();
  if (open.status !== 'open' || !open.session_id || !open.nonce) throw new NoOpenSession();
  const res = await api.checkin(open.session_id, studentId, await keys.signB64(checkinMessage(open.session_id, open.nonce)));
  const skewMs = res.server_time * 1000 - clock.now(); // server - phone
  return {
    sessionId: open.session_id,
    ephId: res.eph_id,
    advertiseName: res.advertise_name,
    serviceUuid: res.service_uuid,
    advertiseUuid: res.advertise_uuid ?? advertiseUuid(res.eph_id),   // older servers: derive it
    discoveryEndsAtMs: (res.discovery_ends_at ?? res.window_ends_at) * 1000 - skewMs,
    reportDeadlineMs: res.report_deadline * 1000 - skewMs,
  };
}

/** Advertise and scan until the window closes; returns the per-peer median RSSI list. Always stops the radio. */
export async function discover(
  radio: Radio, joined: Joined, clock: Clock = systemClock, opts: { minSamples?: number; pollMs?: number } = {},
): Promise<{ neighbours: Neighbour[]; peersHeard: number; discoveryMs: number }> {
  const collector = new NeighbourCollector(joined.ephId);
  const started = clock.now();
  await radio.start(joined.advertiseName, joined.advertiseUuid, (s) => collector.add(s));
  try {
    while (clock.now() < joined.discoveryEndsAtMs) {
      await clock.sleep(Math.min(opts.pollMs ?? 250, Math.max(1, joined.discoveryEndsAtMs - clock.now())));
    }
  } finally {
    await radio.stop();
  }
  return { neighbours: collector.neighbours(opts.minSamples ?? 3), peersHeard: collector.peersHeard, discoveryMs: clock.now() - started };
}

/** Send the signed report, retrying transient failures until the report deadline. */
export async function submitReport(
  api: NetPresenceApi, keys: KeyStore, joined: Joined, studentId: string, neighbours: Neighbour[], clock: Clock = systemClock,
): Promise<{ attempts: number }> {
  const signature = await keys.signB64(reportMessage(joined.sessionId, studentId, neighbours));
  let delay = 500;
  for (let attempts = 1; ; attempts++) {
    try {
      await api.report(joined.sessionId, studentId, neighbours, signature);
      return { attempts };
    } catch (e) {
      const transient = e instanceof ApiError && e.transient;
      if (!transient || clock.now() + delay > joined.reportDeadlineMs) throw e;
      await clock.sleep(delay);
      delay = Math.min(delay * 2, 4000);
    }
  }
}

export interface MarkPresentDeps {
  api: NetPresenceApi; keys: KeyStore; radio: Radio; studentId: string; clock?: Clock;
}

/** The whole student flow behind the single "Mark me present" button. */
export async function markPresent(d: MarkPresentDeps) {
  const clock = d.clock ?? systemClock;
  const joined = await joinSession(d.api, d.keys, d.studentId, clock);
  const found = await discover(d.radio, joined, clock);
  const sent = await submitReport(d.api, d.keys, joined, d.studentId, found.neighbours, clock);
  return { joined, ...found, ...sent };
}
