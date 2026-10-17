import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { SCAN_MASK, SERVICE_PREFIX, advertiseUuid, ephFromUuid } from '../src/ble';

describe('identity in the service UUID', () => {
  it('round-trips the ephemeral id and is a valid 128-bit UUID', () => {
    const u = advertiseUuid('1A2b3C4d');
    expect(u).toBe('6e657470-7265-7365-6e63-65001a2b3c4d');
    expect(u).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
    expect(ephFromUuid(u.toUpperCase())).toBe('1a2b3c4d');        // iOS reports UUIDs upper-case
  });
  it('rejects anything that is not a NetPresence advert', () => {
    expect(ephFromUuid('0000180f-0000-1000-8000-00805f9b34fb')).toBeNull();   // battery service
    expect(ephFromUuid(SERVICE_PREFIX + 'zzzzzzzz')).toBeNull();
    expect(ephFromUuid(SERVICE_PREFIX + '1a2b3c')).toBeNull();
    expect(() => advertiseUuid('nothex!!')).toThrow();
  });
  it('mask keeps exactly the 96-bit prefix', () => {
    const hex = (s: string) => s.replace(/-/g, '');
    const m = hex(SCAN_MASK);
    expect(m.slice(0, 24)).toBe('f'.repeat(24));
    expect(m.slice(24)).toBe('0'.repeat(8));
    expect(hex(SERVICE_PREFIX).length).toBe(24);
  });
  it('matches the server (cross-language vector)', () => {
    const v = JSON.parse(readFileSync(path.resolve(__dirname, '../../../docs/test-vectors.json'), 'utf8'));
    for (const c of v.advertise_uuid) expect(advertiseUuid(c.eph_id)).toBe(c.uuid);
  });
});
