/** BLE lab export, CSV v2 (docs/NETSIM.md): one row per RSSI sample, consumed by backend/netsim/traces.py and tools/fit_pathloss.py. */
export const LAB_HEADER = 't_ms,model,platform,peer_eph,distance_m,orientation,bodies,wall,rssi';
export const ORIENTATIONS = ['hand', 'desk', 'pocket', 'bag'] as const;
export type Orientation = (typeof ORIENTATIONS)[number];

export interface LabContext {
  model: string;
  platform: 'android' | 'ios';
  distanceM: number;
  orientation: Orientation;
  /** people standing between the two phones (0-3) */
  bodies: number;
  /** true when a wall is between them */
  wall: boolean;
}

/** "NP-1a2b3c4d" -> "1a2b3c4d"; anything else -> "" */
export function ephOfName(name: string): string {
  const m = /^NP-([0-9a-f]{8})$/.exec(name);
  return m ? m[1] : '';
}

const clean = (s: string) => s.replace(/[,\r\n]/g, ' ');

export function labRow(tMs: number, peerName: string, rssi: number, c: LabContext): string {
  return [Math.round(tMs), clean(c.model), c.platform, ephOfName(peerName), c.distanceM, c.orientation, c.bodies,
    c.wall ? 1 : 0, rssi].join(',');
}
