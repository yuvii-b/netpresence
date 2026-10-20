import type { Neighbour, RadioSample } from './types';

const NAME = /^NP-([0-9a-f]{8})$/i;
export const MAX_NEIGHBOURS = 200; // server limit

function median(xs: number[]): number {
  const s = [...xs].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m]! : Math.round((s[m - 1]! + s[m]!) / 2);
}

/** Collects advertisements heard during the discovery window and reduces them to one median RSSI per peer. */
export class NeighbourCollector {
  private readonly samples = new Map<string, number[]>();
  constructor(private readonly selfEphId: string) {}

  add(s: RadioSample): void {
    const m = NAME.exec(s.name ?? '');
    if (!m) return;
    const peer = m[1]!.toLowerCase();
    if (peer === this.selfEphId.toLowerCase()) return;
    if (!Number.isFinite(s.rssi) || s.rssi >= 0 || s.rssi < -127) return; // 127 = Android "unavailable", 0 = bogus
    const list = this.samples.get(peer);
    if (list) list.push(Math.round(s.rssi));
    else this.samples.set(peer, [Math.round(s.rssi)]);
  }

  /** Peers heard at least `minSamples` times (one stray packet is not a neighbour), strongest/most-heard first, capped. */
  neighbours(minSamples = 3, max = MAX_NEIGHBOURS): Neighbour[] {
    const out: Neighbour[] = [];
    for (const [peer, xs] of this.samples) {
      if (xs.length >= minSamples) out.push({ peer_id: peer, rssi_median: median(xs), sample_count: xs.length });
    }
    out.sort((a, b) => b.sample_count - a.sample_count || b.rssi_median - a.rssi_median || (a.peer_id < b.peer_id ? -1 : 1));
    return out.slice(0, max);
  }

  get peersHeard(): number {
    return this.samples.size;
  }
}
