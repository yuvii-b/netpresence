import { joinSession, discover, submitReport } from '../../core/src';
import type { Joined, KeyStore, NetPresenceApi, Radio } from '../../core/src';

export type Phase = 'idle' | 'joining' | 'listening' | 'sending' | 'done' | 'error';

/** The student flow, split into visible phases so the UI can show a countdown and a live "phones nearby" count. */
export async function runRollCall(d: {
  api: NetPresenceApi; keys: KeyStore; radio: Radio; studentId: string;
  onPhase: (p: Phase, joined?: Joined) => void; onNearby: (n: number) => void;
}) {
  d.onPhase('joining');
  const joined = await joinSession(d.api, d.keys, d.studentId);
  d.onPhase('listening', joined);

  const seen = new Set<string>();
  const counting: Radio = {
    start: (name, uuid, cb) => d.radio.start(name, uuid, (s) => {
      if (s.name !== joined.advertiseName && !seen.has(s.name)) { seen.add(s.name); d.onNearby(seen.size); }
      cb(s);
    }),
    stop: () => d.radio.stop(),
  };
  const found = await discover(counting, joined);

  d.onPhase('sending', joined);
  const sent = await submitReport(d.api, d.keys, joined, d.studentId, found.neighbours);
  d.onPhase('done', joined);
  return { peersHeard: found.peersHeard, attempts: sent.attempts };
}
