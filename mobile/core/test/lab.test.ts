import { describe, expect, it } from 'vitest';
import { LAB_HEADER, ephOfName, labRow } from '../src';

const ctx = { model: 'Pixel 6, test', platform: 'android' as const, distanceM: 2, orientation: 'desk' as const, bodies: 1, wall: true };

describe('BLE lab CSV v2', () => {
  it('has the columns netsim/traces.py expects', () => {
    expect(LAB_HEADER.split(',')).toEqual(['t_ms', 'model', 'platform', 'peer_eph', 'distance_m', 'orientation', 'bodies', 'wall', 'rssi']);
  });
  it('writes one comma-safe row per sample', () => {
    const row = labRow(1234.6, 'NP-0a1b2c3d', -67, ctx);
    expect(row).toBe('1235,Pixel 6  test,android,0a1b2c3d,2,desk,1,1,-67');
    expect(row.split(',').length).toBe(LAB_HEADER.split(',').length);
  });
  it('ignores names that are not NetPresence ids', () => {
    expect(ephOfName('NP-xyz')).toBe('');
    expect(ephOfName('iPhone')).toBe('');
    expect(ephOfName('NP-ffffffff')).toBe('ffffffff');
  });
});
