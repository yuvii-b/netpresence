import React, { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Pressable, SafeAreaView, StatusBar, StyleSheet, Text, TextInput, View } from 'react-native';
import { NetPresenceApi, NoOpenSession, enroll, markPresent } from '../core/src';
import Lab from './src/Lab';
import { NativeRadio, deviceModel, nativeKeys } from './src/native';
import { Profile, clearProfile, loadProfile, saveProfile } from './src/storage';

type Phase = 'idle' | 'working' | 'done' | 'error';

export default function App() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [lab, setLab] = useState(false);
  const [form, setForm] = useState<Profile>({ baseUrl: 'https://', studentId: '', name: '' });
  const [phase, setPhase] = useState<Phase>('idle');
  const [msg, setMsg] = useState('');
  const radio = useRef(new NativeRadio()).current;

  useEffect(() => { loadProfile().then((p) => { setProfile(p); setLoaded(true); }); }, []);
  if (!loaded) return <ActivityIndicator style={{ flex: 1 }} />;

  const doEnroll = async () => {
    setPhase('working'); setMsg('Registering this phone…');
    try {
      const base = form.baseUrl.trim().replace(/\/+$/, '');
      await enroll(new NetPresenceApi(base), nativeKeys, { studentId: form.studentId.trim(), name: form.name.trim(), model: await deviceModel() });
      const p = { ...form, baseUrl: base, studentId: form.studentId.trim(), name: form.name.trim() };
      await saveProfile(p); setProfile(p); setPhase('idle'); setMsg('');
    } catch (e: any) { setPhase('error'); setMsg(e?.message ?? String(e)); }
  };

  const mark = async () => {
    if (!profile) return;
    setPhase('working'); setMsg('Looking for the roll call…');
    try {
      const r = await markPresent({ api: new NetPresenceApi(profile.baseUrl), keys: nativeKeys, radio, studentId: profile.studentId });
      setPhase('done');
      setMsg(`Sent. Heard ${r.peersHeard} nearby phones. Your teacher's screen will show your status.`);
    } catch (e: any) {
      setPhase('error');
      setMsg(e instanceof NoOpenSession ? 'No roll call is open yet. Try again when your teacher starts it.' : radio.lastError ? `Bluetooth problem (${radio.lastError}). Check Bluetooth is on.` : e?.message ?? String(e));
    }
  };

  return (
    <SafeAreaView style={s.root}>
      <StatusBar barStyle="dark-content" />
      {lab ? (
        <><Lab /><Pressable onPress={() => setLab(false)}><Text style={s.link}>Back</Text></Pressable></>
      ) : !profile ? (
        <View style={s.box}>
          <Text style={s.h}>NetPresence</Text>
          <Text>One-time setup for this phone.</Text>
          <TextInput style={s.in} placeholder="Server URL" autoCapitalize="none" value={form.baseUrl} onChangeText={(baseUrl) => setForm({ ...form, baseUrl })} />
          <TextInput style={s.in} placeholder="Roll number" autoCapitalize="characters" value={form.studentId} onChangeText={(studentId) => setForm({ ...form, studentId })} />
          <TextInput style={s.in} placeholder="Name" value={form.name} onChangeText={(name) => setForm({ ...form, name })} />
          <Pressable style={s.btn} onPress={doEnroll} disabled={phase === 'working'}><Text style={s.btnT}>Register</Text></Pressable>
          {msg ? <Text style={phase === 'error' ? s.err : undefined}>{msg}</Text> : null}
        </View>
      ) : (
        <View style={s.box}>
          <Text style={s.h}>{profile.name}</Text>
          <Text>{profile.studentId}</Text>
          <Pressable style={[s.big, phase === 'working' && { opacity: 0.5 }]} onPress={mark} disabled={phase === 'working'}>
            <Text style={s.bigT}>{phase === 'working' ? 'Working…' : phase === 'done' ? 'Done ✓' : 'Mark me present'}</Text>
          </Pressable>
          {msg ? <Text style={phase === 'error' ? s.err : undefined}>{msg}</Text> : null}
          <Text style={s.hint}>Keep this screen open and Bluetooth on for about 45 seconds.</Text>
          <Pressable onPress={() => setLab(true)}><Text style={s.link}>BLE lab</Text></Pressable>
          <Pressable onPress={async () => { await clearProfile(); setProfile(null); setPhase('idle'); setMsg(''); }}><Text style={s.link}>Switch student</Text></Pressable>
        </View>
      )}
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#fff' }, box: { padding: 20, gap: 12 }, h: { fontSize: 26, fontWeight: '700' },
  in: { borderWidth: 1, borderColor: '#999', borderRadius: 8, padding: 10, fontSize: 16 },
  btn: { backgroundColor: '#1a56db', padding: 14, borderRadius: 8, alignItems: 'center' }, btnT: { color: '#fff', fontSize: 16, fontWeight: '600' },
  big: { backgroundColor: '#0e9f6e', paddingVertical: 36, borderRadius: 16, alignItems: 'center', marginTop: 20 }, bigT: { color: '#fff', fontSize: 26, fontWeight: '700' },
  err: { color: '#b00020' }, hint: { color: '#666' }, link: { color: '#1a56db', padding: 8 },
});
