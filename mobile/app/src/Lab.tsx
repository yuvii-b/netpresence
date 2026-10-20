import React, { useRef, useState } from 'react';
import { Platform, Pressable, ScrollView, Share, StyleSheet, Text, View } from 'react-native';
import { LAB_HEADER, ORIENTATIONS, advertiseUuid, labRow, type Orientation } from '../../core/src';
import { NativeRadio, deviceModel, describeRadioError } from './native';
import { useTheme } from './theme';
import { Banner, Button, Card, Field } from './ui';

/**
 * BLE lab (plan phase 0.3). One phone advertises, the others log at known distances; export
 * CSV v2 rows (t_ms,model,platform,peer_eph,distance_m,orientation,bodies,wall,rssi) for `python -m tools.fit_pathloss`
 * and the network simulator's trace-driven channel (backend/netsim/traces.py).
 */
export default function Lab() {
  const t = useTheme();
  const radio = useRef(new NativeRadio()).current;
  const rows = useRef<string[]>([]);
  const [dist, setDist] = useState('1');
  const [orient, setOrient] = useState<Orientation>('desk');
  const [bodies, setBodies] = useState(0);
  const [wall, setWall] = useState(false);
  const [running, setRunning] = useState(false);
  const [count, setCount] = useState(0);
  const [peers, setPeers] = useState<Record<string, number>>({});
  const [err, setErr] = useState('');

  const start = async () => {
    setErr('');
    try {
      const model = await deviceModel();
      const t0 = Date.now();
      const ctx = { model, platform: Platform.OS === 'ios' ? ('ios' as const) : ('android' as const),
        distanceM: parseFloat(dist) || 0, orientation: orient, bodies, wall };
      rows.current = []; setCount(0); setPeers({});
      const eph = Array.from({ length: 8 }, () => '0123456789abcdef'[Math.floor(Math.random() * 16)]).join('');
      await radio.start(`NP-${eph}`, advertiseUuid(eph), (s) => {
        if (s.rssi >= 0) return;
        rows.current.push(labRow(Date.now() - t0, s.name, s.rssi, ctx));
        if (rows.current.length % 10 === 0) setCount(rows.current.length);
        setPeers((p) => ({ ...p, [s.name]: (p[s.name] ?? 0) + 1 }));
      });
      setRunning(true);
    } catch (e: any) { setErr(e?.message ?? String(e)); }
  };
  const stop = async () => { await radio.stop(); setRunning(false); setCount(rows.current.length); };
  const share = () => Share.share({ message: [LAB_HEADER, ...rows.current].join('\n') });

  return (
    <ScrollView contentContainerStyle={s.box}>
      <Text style={[s.h, { color: t.text }]}>BLE lab</Text>
      <Text style={{ color: t.sub, lineHeight: 20 }}>Put two phones a known distance apart, start logging on both, then export the CSV.</Text>
      <Card style={{ gap: 14 }}>
        <Field label="DISTANCE TO THE OTHER PHONE (METRES)" value={dist} onChangeText={setDist} keyboardType="decimal-pad" editable={!running} />
        <Pick label="HOW THE PHONES ARE HELD" options={[...ORIENTATIONS]} value={orient} onPick={(v) => setOrient(v as Orientation)} off={running} />
        <Pick label="PEOPLE BETWEEN THE PHONES" options={['0', '1', '2', '3']} value={String(bodies)} onPick={(v) => setBodies(Number(v))} off={running} />
        <Pick label="WALL BETWEEN THE PHONES" options={['no', 'yes']} value={wall ? 'yes' : 'no'} onPick={(v) => setWall(v === 'yes')} off={running} />
        <Button title={running ? 'Stop logging' : 'Start logging'} onPress={running ? stop : start} />
        <Text style={{ color: t.text, fontWeight: '700' }}>{count} samples</Text>
        {Object.entries(peers).map(([k, v]) => <Text key={k} style={{ color: t.sub }}>{k}: {v}</Text>)}
        <Button kind="ghost" title="Export CSV" onPress={share} disabled={running || !rows.current.length} />
      </Card>
      {err || radio.lastError ? <Banner kind="err" text={err || describeRadioError(radio.lastError || '')} /> : null}
    </ScrollView>
  );
}
function Pick({ label, options, value, onPick, off }: { label: string; options: string[]; value: string; onPick: (v: string) => void; off: boolean }) {
  const t = useTheme();
  return (
    <View style={{ gap: 6 }}>
      <Text style={{ color: t.sub, fontSize: 12, fontWeight: '700' }}>{label}</Text>
      <View style={{ flexDirection: 'row', gap: 8, flexWrap: 'wrap' }}>
        {options.map((o) => (
          <Pressable key={o} disabled={off} onPress={() => onPick(o)} accessibilityRole="button" accessibilityState={{ selected: o === value }}
            style={{ paddingVertical: 8, paddingHorizontal: 14, borderRadius: 18, borderWidth: 1, borderColor: o === value ? t.text : t.sub, opacity: off ? 0.5 : 1 }}>
            <Text style={{ color: t.text, fontWeight: o === value ? '800' : '500' }}>{o}</Text>
          </Pressable>
        ))}
      </View>
    </View>
  );
}
const s = StyleSheet.create({ box: { padding: 20, gap: 14 }, h: { fontSize: 28, fontWeight: '800' } });
