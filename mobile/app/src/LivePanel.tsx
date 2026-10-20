import React, { useEffect, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import type { LiveDiag } from '../../core/src';
import { useTheme } from './theme';
import { Card } from './ui';

const RADIO = { off: ['Off', 'sub'], starting: ['Starting…', 'warn'], on: ['On', 'ok'], error: ['Problem', 'err'] } as const;

/** "What is happening on this phone right now": Bluetooth, who it hears, what it has sent, and a time-stamped log. */
export default function LivePanel({ d }: { d: LiveDiag }) {
  const t = useTheme();
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const i = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(i); }, []);
  const [label, tone] = RADIO[d.radio];
  const ago = d.lastSentAt ? `${Math.max(0, Math.round((now - d.lastSentAt) / 1000))} s ago` : 'none yet';
  const Row = ({ k, v, c }: { k: string; v: string; c?: string }) => (
    <View style={s.row}><Text style={{ color: t.sub, fontSize: 13 }}>{k}</Text><Text style={{ color: c ?? t.text, fontSize: 13, fontWeight: '700' }}>{v}</Text></View>
  );
  return (
    <Card style={{ gap: 8 }}>
      <Text style={{ color: t.text, fontSize: 15, fontWeight: '800' }}>What's happening</Text>
      <Row k="Bluetooth" v={label} c={t[tone]} />
      {d.advertiseAs ? <Row k="Broadcasting as" v={d.advertiseAs} /> : null}
      <Row k="Phones heard" v={String(d.peers.length)} c={d.peers.length ? t.ok : t.sub} />
      {d.peers.slice(0, 8).map((p) => (
        <Text key={p.id} style={[s.mono, { color: t.sub }]}>  {p.id}   {p.rssi} dBm   {p.n} samples</Text>
      ))}
      {d.peers.length > 8 ? <Text style={[s.mono, { color: t.sub }]}>  + {d.peers.length - 8} more</Text> : null}
      <Row k="Adverts heard" v={`${d.adverts}${d.foreign ? `  (+${d.foreign} other class, ignored)` : ''}`} />
      <Row k="Reports to server" v={`${d.sent} sent, ${d.failed} failed, last ${ago}`} c={d.failed ? t.warn : t.text} />
      <View style={[s.log, { backgroundColor: t.input, borderColor: t.border }]}>
        {d.log.slice(-12).map((l, i) => <Text key={i} style={[s.mono, { color: t.text }]}>{l}</Text>)}
        {d.log.length === 0 ? <Text style={[s.mono, { color: t.sub }]}>nothing yet</Text> : null}
      </View>
    </Card>
  );
}

const s = StyleSheet.create({
  row: { flexDirection: 'row', justifyContent: 'space-between', gap: 12 },
  mono: { fontFamily: 'monospace', fontSize: 11, lineHeight: 16 },
  log: { borderWidth: 1, borderRadius: 12, padding: 10, gap: 2 },
});
