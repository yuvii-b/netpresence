import { describe, expect, it } from 'vitest';
import { MAX_NEIGHBOURS, NeighbourCollector } from '../src/aggregate';

const feed = (c: NeighbourCollector, name: string, ...rssi: number[]) => rssi.forEach((r) => c.add({ name, rssi: r }));

describe('NeighbourCollector', () => {
  it('takes the median per peer and counts samples', () => {
    const c = new NeighbourCollector('aaaaaaaa');
    feed(c, 'NP-0a1b2c3d', -70, -60, -80, -65, -75); // sorted -80 -75 -70 -65 -60 -> -70
    expect(c.neighbours()).toEqual([{ peer_id: '0a1b2c3d', rssi_median: -70, sample_count: 5 }]);
  });
  it('even sample count averages the middle pair (rounded)', () => {
    const c = new NeighbourCollector('aaaaaaaa');
    feed(c, 'NP-0a1b2c3d', -70, -60, -66, -64); // middle -66,-64 -> -65
    expect(c.neighbours()[0]!.rssi_median).toBe(-65);
  });
  it('ignores itself, foreign names, and bogus RSSI (127, 0, positive, NaN)', () => {
    const c = new NeighbourCollector('AAAAAAAA');
    feed(c, 'NP-aaaaaaaa', -50, -50, -50); // self (case-insensitive)
    feed(c, 'JBL Speaker', -50, -50, -50);
    feed(c, 'NP-zzzzzzzz', -50, -50, -50); // not hex
    feed(c, 'NP-12345678', 127, 0, 5, NaN, -200); // all invalid
    expect(c.neighbours(1)).toEqual([]);
  });
  it('peer ids are normalised to lower case and merged', () => {
    const c = new NeighbourCollector('aaaaaaaa');
    feed(c, 'NP-ABCDEF01', -60, -60);
    feed(c, 'NP-abcdef01', -60);
    expect(c.neighbours()).toEqual([{ peer_id: 'abcdef01', rssi_median: -60, sample_count: 3 }]);
  });
  it('one stray packet is not a neighbour (minSamples)', () => {
    const c = new NeighbourCollector('aaaaaaaa');
    feed(c, 'NP-0a1b2c3d', -60, -60);
    expect(c.neighbours(3)).toEqual([]);
    expect(c.peersHeard).toBe(1);
  });
  it('is capped at the server limit, most-heard first', () => {
    const c = new NeighbourCollector('aaaaaaaa');
    for (let i = 0; i < MAX_NEIGHBOURS + 20; i++) feed(c, `NP-${i.toString(16).padStart(8, '0')}`, -60, -60, -60, ...(i === 7 ? [-60, -60] : []));
    const n = c.neighbours();
    expect(n).toHaveLength(MAX_NEIGHBOURS);
    expect(n[0]!.peer_id).toBe('00000007');
  });
});
