/**
 * On-air identity: the 32-bit ephemeral id is carried INSIDE the advertised 128-bit service UUID,
 *   6e657470-7265-7365-6e63-6500XXXXXXXX     (fixed 96-bit NetPresence prefix + 8 hex id)
 * so one 21-byte advertisement (flags + UUID) identifies a phone on Android and iOS alike: no device name,
 * no manufacturer data, no scan response that can be lost to a collision in a crowded room.
 * Android scanners filter on the prefix with a UUID mask; iOS scanners match the prefix in code.
 */
export const SERVICE_PREFIX = '6e657470-7265-7365-6e63-6500';
export const SCAN_MASK = 'ffffffff-ffff-ffff-ffff-ffff00000000';

const EPH = /^[0-9a-f]{8}$/;

export function advertiseUuid(ephId: string): string {
  const e = ephId.toLowerCase();
  if (!EPH.test(e)) throw new Error(`bad ephemeral id: ${ephId}`);
  return SERVICE_PREFIX + e;
}

/** The ephemeral id inside a heard service UUID, or null if it is not a NetPresence advert. */
export function ephFromUuid(uuid: string): string | null {
  const u = uuid.toLowerCase();
  if (u.length !== 36 || !u.startsWith(SERVICE_PREFIX)) return null;
  const e = u.slice(SERVICE_PREFIX.length);
  return EPH.test(e) ? e : null;
}
