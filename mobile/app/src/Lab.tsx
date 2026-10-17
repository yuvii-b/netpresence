import React, { useRef, useState } from 'react';
import { ScrollView, Share, StyleSheet, Text } from 'react-native';
import { advertiseUuid } from '../../core/src';
import { NativeRadio, deviceModel, describeRadioError } from './native';
import { useTheme } from './theme';
import { Banner, Button, Card, Field } from './ui';

/**
 * BLE lab (plan phase 0.3). One phone advertises, the others log at known distances; export
 * "model,distance_m,rssi" rows for `python -m tools.fit_pathloss`.
 */
export default function Lab() {
  const t = useTheme();
  const radio = useRef(new NativeRadio()).current;
  const rows = useRef<string[]>([]);
  const [dist, setDist] = useState('1');
  const [running, setRunning] = useState(false);
  const [count, setCount] = useState(0);
  const [peers, setPeers] = useState<Record<string, number>>({});
  const [err, setErr] = useState('');

  const start = async () => {
    setErr('');
    try {
      const model = (await deviceModel()).replace(/,/g, ' ');
      rows.current = []; setCount(0); setPeers({});
      const eph = Array.from({ length: 8 }, () => '0123456789abcdef'[Math.floor(Math.random() * 16)]).join('');
      await radio.start(`NP-${eph}`, advertiseUuid(eph), (s) => {
        if (s.rssi >= 0) return;
        rows.current.push(`${model},${dist},${s.rssi}`);
        if (rows.current.length % 10 === 0) setCount(rows.current.length);
        setPeers((p) => ({ ...p, [s.name]: (p[s.name] ?? 0) + 1 }));
      });
      setRunning(true);
    } catch (e: any) { setErr(e?.message ?? String(e)); }
  };
  const stop = async () => { await radio.stop(); setRunning(false); setCount(rows.current.length); };
  const share = () => Share.share({ message: ['model,distance_m,rssi', ...rows.current].join('\n') });

  return (
    <ScrollView contentContainerStyle={s.box}>
      <Text style={[s.h, { color: t.text }]}>BLE lab</Text>
      <Text style={{ color: t.sub, lineHeight: 20 }}>Put two phones a known distance apart, start logging on both, then export the CSV.</Text>
      <Card style={{ gap: 14 }}>
        <Field label="DISTANCE TO THE OTHER PHONE (METRES)" value={dist} onChangeText={setDist} keyboardType="decimal-pad" editable={!running} />
        <Button title={running ? 'Stop logging' : 'Start logging'} onPress={running ? stop : start} />
        <Text style={{ color: t.text, fontWeight: '700' }}>{count} samples</Text>
        {Object.entries(peers).map(([k, v]) => <Text key={k} style={{ color: t.sub }}>{k}: {v}</Text>)}
        <Button kind="ghost" title="Export CSV" onPress={share} disabled={running || !rows.current.length} />
      </Card>
      {err || radio.lastError ? <Banner kind="err" text={err || describeRadioError(radio.lastError || '')} /> : null}
    </ScrollView>
  );
}
const s = StyleSheet.create({ box: { padding: 20, gap: 14 }, h: { fontSize: 28, fontWeight: '800' } });
