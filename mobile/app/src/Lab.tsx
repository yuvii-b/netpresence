import React, { useRef, useState } from 'react';
import { Button, ScrollView, Share, StyleSheet, Text, TextInput, View } from 'react-native';
import { NativeRadio, deviceModel } from './native';

/**
 * BLE lab logger (plan phase 0.3). Put one phone advertising and others measuring at known distances, then export
 * "model,distance_m,rssi" rows for `python -m tools.fit_pathloss`.
 */
export default function Lab() {
  const radio = useRef(new NativeRadio()).current;
  const rows = useRef<string[]>([]);
  const [dist, setDist] = useState('1');
  const [running, setRunning] = useState(false);
  const [count, setCount] = useState(0);
  const [peers, setPeers] = useState<Record<string, number>>({});

  const start = async () => {
    const model = (await deviceModel()).replace(/,/g, ' ');
    rows.current = [];
    setCount(0); setPeers({});
    await radio.start('NP-LAB00000', '6e657470-7265-7365-6e63-650000000001', (s) => {
      if (s.rssi >= 0) return;
      rows.current.push(`${model},${dist},${s.rssi}`);
      if (rows.current.length % 10 === 0) setCount(rows.current.length);
      setPeers((p) => ({ ...p, [s.name]: (p[s.name] ?? 0) + 1 }));
    });
    setRunning(true);
  };
  const stop = async () => { await radio.stop(); setRunning(false); setCount(rows.current.length); };
  const share = () => Share.share({ message: ['model,distance_m,rssi', ...rows.current].join('\n') });

  return (
    <ScrollView contentContainerStyle={s.box}>
      <Text style={s.h}>BLE lab</Text>
      <Text>Distance to the other phone (metres)</Text>
      <TextInput style={s.in} value={dist} onChangeText={setDist} keyboardType="decimal-pad" editable={!running} />
      <Button title={running ? 'Stop' : 'Start logging'} onPress={running ? stop : start} />
      <Text>{count} samples</Text>
      {Object.entries(peers).map(([k, v]) => <Text key={k}>{k}: {v}</Text>)}
      <Button title="Export CSV" onPress={share} disabled={running || !rows.current.length} />
      {radio.lastError ? <Text style={s.err}>{radio.lastError}</Text> : null}
    </ScrollView>
  );
}
const s = StyleSheet.create({
  box: { padding: 16, gap: 10 }, h: { fontSize: 22, fontWeight: '700' },
  in: { borderWidth: 1, borderColor: '#999', borderRadius: 6, padding: 8 }, err: { color: '#b00' },
});
