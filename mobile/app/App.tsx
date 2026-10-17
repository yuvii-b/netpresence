import React, { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Platform, Pressable, SafeAreaView, ScrollView, StatusBar, StyleSheet, Text, Vibration, View, useColorScheme } from 'react-native';
import { ApiError, NetPresenceApi, NoOpenSession, enroll } from '../core/src';
import { Phase, runRollCall } from './src/flow';
import Lab from './src/Lab';
import { NativeRadio, deviceModel, nativeKeys, setKeepAwake } from './src/native';
import RollButton from './src/RollButton';
import { Profile, clearProfile, loadProfile, saveProfile } from './src/storage';
import { useTheme } from './src/theme';
import { Banner, Button, Card, Chip, Field } from './src/ui';

// Test-build convenience: add a missing scheme, and use plain http for LAN / Tailscale addresses
// (a leftover "https://" on a laptop IP is the most common reason the connection fails).
const normalizeUrl = (raw: string) => {
  let u = raw.trim().replace(/\/+$/, '');
  if (!/^https?:\/\//i.test(u)) u = 'http://' + u;
  if (/^https:\/\/(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|100\.)/.test(u)) u = u.replace(/^https:/, 'http:');
  return u;
};

export default function App() {
  const t = useTheme();
  const dark = useColorScheme() === 'dark';
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [screen, setScreen] = useState<'main' | 'lab'>('main');

  useEffect(() => { loadProfile().then((p) => { setProfile(p); setLoaded(true); }); }, []);

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: t.bg }}>
      <StatusBar barStyle={dark ? 'light-content' : 'dark-content'} backgroundColor={t.bg} />
      {!loaded ? <ActivityIndicator style={{ flex: 1 }} color={t.primary} />
        : screen === 'lab' ? <><Lab /><View style={{ padding: 16 }}><Button kind="ghost" title="Back" onPress={() => setScreen('main')} /></View></>
        : !profile ? <Setup onDone={setProfile} />
        : <Home profile={profile} onLab={() => setScreen('lab')} onSwitch={async () => { await clearProfile(); setProfile(null); }} />}
    </SafeAreaView>
  );
}

function Mark() {
  const t = useTheme();
  return (
    <View style={[s.mark, { backgroundColor: t.primary }]}>
      <View style={[s.dot, { backgroundColor: t.primaryText }]} />
      <View style={[s.arc, { borderColor: t.primaryText, width: 34, height: 34, borderRadius: 17 }]} />
      <View style={[s.arc, { borderColor: t.primaryText, width: 52, height: 52, borderRadius: 26, opacity: 0.55 }]} />
    </View>
  );
}

function Setup({ onDone }: { onDone: (p: Profile) => void }) {
  const t = useTheme();
  const [form, setForm] = useState<Profile>({ baseUrl: 'http://192.168.', studentId: '', name: '' });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const ready = form.studentId.trim().length > 0 && form.name.trim().length > 0 && form.baseUrl.trim().length > 8;

  const go = async () => {
    setBusy(true); setErr('');
    const base = normalizeUrl(form.baseUrl);
    const api = new NetPresenceApi(base);
    try {
      await api.openSession(); // proves the phone can reach the server before we try to register
    } catch (e: any) {
      setBusy(false);
      setErr(e instanceof ApiError && e.status === 0
        ? `Can't reach ${base}\n\nOpen that address followed by /docs in this phone's browser. If it doesn't load there either, it's the Wi-Fi or the laptop firewall, not the app. Same Wi-Fi? Server started with --host 0.0.0.0?`
        : `The server at ${base} answered with an error: ${e?.message ?? e}`);
      return;
    }
    try {
      await enroll(api, nativeKeys, { studentId: form.studentId.trim(), name: form.name.trim(), model: await deviceModel() });
      const p = { baseUrl: base, studentId: form.studentId.trim(), name: form.name.trim() };
      await saveProfile(p); onDone(p);
    } catch (e: any) {
      setErr(`Registration failed: ${e?.message ?? String(e)}`);
    } finally { setBusy(false); }
  };

  return (
    <ScrollView contentContainerStyle={s.page} keyboardShouldPersistTaps="handled">
      <View style={{ alignItems: 'center', gap: 10, marginTop: 24 }}>
        <Mark />
        <Text style={[s.title, { color: t.text }]}>NetPresence</Text>
        <Text style={[s.lead, { color: t.sub }]}>Attendance in one tap.{'\n'}Set up this phone once.</Text>
      </View>
      <Card style={{ gap: 16 }}>
        <Field label="ROLL NUMBER" placeholder="e.g. 21CS042" autoCapitalize="characters" value={form.studentId} onChangeText={(studentId) => setForm({ ...form, studentId })} />
        <Field label="FULL NAME" placeholder="As on the register" value={form.name} onChangeText={(name) => setForm({ ...form, name })} />
        <Field label="SERVER ADDRESS" placeholder="http://192.168.1.4:8000" autoCapitalize="none" keyboardType="url" value={form.baseUrl}
          onChangeText={(baseUrl) => setForm({ ...form, baseUrl })} hint="Your teacher or test laptop. Use http:// for a laptop on the same Wi-Fi." />
        {err ? <Banner kind="err" text={err} /> : null}
        <Button title={busy ? 'Setting up…' : 'Get started'} onPress={go} disabled={busy || !ready} />
      </Card>
      <Text style={[s.fine, { color: t.sub }]}>This phone creates a private key that never leaves it. It proves the attendance is really yours.</Text>
    </ScrollView>
  );
}

function Home({ profile, onLab, onSwitch }: { profile: Profile; onLab: () => void; onSwitch: () => void }) {
  const t = useTheme();
  const radio = useRef(new NativeRadio()).current;
  const [phase, setPhase] = useState<Phase>('idle');
  const [endsAt, setEndsAt] = useState(0);
  const [now, setNow] = useState(Date.now());
  const [nearby, setNearby] = useState(0);
  const [msg, setMsg] = useState('');
  const [heard, setHeard] = useState(0);
  const [menu, setMenu] = useState(false);

  useEffect(() => {
    if (phase !== 'listening') return;
    const i = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(i);
  }, [phase]);

  const mark = async () => {
    setMsg(''); setNearby(0); setHeard(0);
    setKeepAwake(true);
    try {
      const r = await runRollCall({
        api: new NetPresenceApi(profile.baseUrl), keys: nativeKeys, radio, studentId: profile.studentId,
        onPhase: (p, j) => { setPhase(p); if (j) setEndsAt(j.discoveryEndsAtMs); },
        onNearby: setNearby,
      });
      setHeard(r.peersHeard); Vibration.vibrate(Platform.OS === 'android' ? [0, 60, 60, 60] : 60);
    } catch (e: any) {
      setPhase('error');
      setMsg(e instanceof NoOpenSession ? 'No roll call is open yet. Wait for your teacher to start it, then tap again.'
        : radio.lastError ? `Bluetooth problem (${radio.lastError}). Make sure Bluetooth is on and allowed for this app.`
        : e instanceof ApiError && e.status === 0 ? `Lost connection to ${profile.baseUrl}. Check your Wi-Fi and try again.`
        : e?.message ?? String(e));
    } finally { setKeepAwake(false); }
  };

  const secondsLeft = Math.ceil((endsAt - now) / 1000);
  const status =
    phase === 'idle' ? 'Ready when your teacher starts the roll call' :
    phase === 'joining' ? 'Joining the roll call…' :
    phase === 'listening' ? 'Listening for nearby phones' :
    phase === 'sending' ? 'Sending your attendance…' :
    phase === 'done' ? 'You\'re marked present' : 'Something went wrong';

  return (
    <ScrollView contentContainerStyle={s.page}>
      <View style={s.head}>
        <View>
          <Text style={[s.hello, { color: t.sub }]}>Hello,</Text>
          <Text style={[s.name, { color: t.text }]} numberOfLines={1}>{profile.name}</Text>
        </View>
        <Pressable accessibilityLabel="Menu" onPress={() => setMenu(!menu)} hitSlop={12}><Text style={{ color: t.sub, fontSize: 28 }}>⋯</Text></Pressable>
      </View>
      <View style={{ flexDirection: 'row', gap: 8 }}><Chip text={profile.studentId} /><Chip text={phase === 'done' ? 'Sent' : 'Not yet marked'} tone={phase === 'done' ? 'ok' : 'neutral'} /></View>

      {menu && (
        <Card style={{ gap: 10 }}>
          <Button kind="ghost" title="BLE lab (signal tests)" onPress={onLab} />
          <Button kind="ghost" title="Switch student" onPress={onSwitch} />
        </Card>
      )}

      <RollButton phase={phase} secondsLeft={secondsLeft} onPress={mark} />

      <Text style={[s.status, { color: t.text }]}>{status}</Text>
      {phase === 'listening' && (<>
        <View style={{ alignSelf: 'center' }}><Chip text={`${nearby} phone${nearby === 1 ? '' : 's'} nearby`} tone={nearby > 0 ? 'ok' : 'neutral'} /></View>
        <Banner kind="warn" text="Keep this screen on and stay seated until the countdown ends." />
      </>)}
      {phase === 'done' && <Banner kind="ok" text={`Heard ${heard} phone${heard === 1 ? '' : 's'} around you. Your teacher confirms the final list.`} />}
      {phase === 'error' && (<><Banner kind="err" text={msg} /><Button title="Try again" onPress={mark} /></>)}
      {phase === 'done' && <Button kind="ghost" title="Done" onPress={() => setPhase('idle')} />}
    </ScrollView>
  );
}

const s = StyleSheet.create({
  page: { padding: 20, gap: 16, paddingBottom: 40 },
  title: { fontSize: 30, fontWeight: '800', letterSpacing: -0.5 },
  lead: { fontSize: 15, textAlign: 'center', lineHeight: 22 },
  fine: { fontSize: 12, textAlign: 'center', lineHeight: 18, paddingHorizontal: 12 },
  head: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginTop: 8 },
  hello: { fontSize: 14 }, name: { fontSize: 26, fontWeight: '800', maxWidth: 280 },
  status: { fontSize: 18, fontWeight: '700', textAlign: 'center' },
  mark: { width: 76, height: 76, borderRadius: 22, alignItems: 'center', justifyContent: 'center' },
  dot: { width: 10, height: 10, borderRadius: 5, position: 'absolute' },
  arc: { position: 'absolute', borderWidth: 3, borderLeftColor: 'transparent', borderBottomColor: 'transparent', transform: [{ rotate: '-45deg' }] },
});
