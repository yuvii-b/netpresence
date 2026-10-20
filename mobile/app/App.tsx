import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Alert, Platform, Pressable, SafeAreaView, ScrollView, Share, StatusBar, StyleSheet, Text, Vibration, View, useColorScheme } from 'react-native';
import { ApiError, DiagBoard, LIVE_BEST_AFTER_S, NetPresenceApi, StudentRunner, TeacherRoll, attendanceCsv, enroll, sheetCsv } from '../core/src';
import type { AttendanceSheet, LiveDiag, StudentState, SubjectInfo, TeacherLive } from '../core/src';
import LivePanel from './src/LivePanel';
import Lab from './src/Lab';
import { NativeRadio, confirmBiometric, deviceModel, installId, nativeKeys, setKeepAwake } from './src/native';
import { Profile, clearProfile, clearTeacher, loadProfile, loadServer, loadTeacher, saveProfile, saveServer, saveTeacher } from './src/storage';
import { Theme, useTheme } from './src/theme';
import { Banner, Button, Card, Chip, Field } from './src/ui';

// Add a missing scheme, and use plain http for LAN / Tailscale addresses (a leftover "https://" on a laptop IP is the
// most common reason the connection fails).
const normalizeUrl = (raw: string) => {
  let u = raw.trim().replace(/\/+$/, '');
  if (!/^https?:\/\//i.test(u)) u = 'http://' + u;
  if (/^https:\/\/(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|100\.)/.test(u)) u = u.replace(/^https:/, 'http:');
  return u;
};
/** Haptics are cosmetic: a missing permission or a phone without a vibrator must never take the app down. */
const buzz = (p: number | number[]) => { try { Vibration.vibrate(p); } catch { /* cosmetic */ } };
const unreachable = (base: string) =>
  `Can't reach ${base}\n\nOpen that address followed by /docs in this phone's browser. If it doesn't load there either, it's the Wi-Fi or the laptop firewall, not the app.`;
const explain = (e: unknown, base: string) =>
  e instanceof ApiError && e.status === 0 ? unreachable(base) : e instanceof Error ? e.message : String(e);

type Route = { name: 'welcome' } | { name: 'student-setup' } | { name: 'student'; profile: Profile; fresh: boolean }
  | { name: 'teacher-login' } | { name: 'teacher-subjects'; base: string; token: string; teacher: string; subjects: SubjectInfo[] }
  | { name: 'teacher-room'; base: string; token: string; subject: SubjectInfo } | { name: 'teacher-sheet'; from: Extract<Route, { name: 'teacher-subjects' }>; subject: SubjectInfo } | { name: 'lab' };

export default function App() {
  const t = useTheme();
  const dark = useColorScheme() === 'dark';
  const [route, setRoute] = useState<Route | null>(null);

  // A phone that is already registered goes straight to the student screen: no tap, no login.
  useEffect(() => {
    (async () => {
      const p = await loadProfile();
      if (p) return setRoute({ name: 'student', profile: p, fresh: false });
      const tsess = await loadTeacher();               // a teacher stays signed in: straight to the subjects
      if (tsess) {
        try {
          const subjects = await new NetPresenceApi(tsess.baseUrl).teacherSubjects(tsess.token);
          return setRoute({ name: 'teacher-subjects', base: tsess.baseUrl, token: tsess.token, teacher: tsess.name, subjects });
        } catch (e) {
          if (e instanceof ApiError && e.status === 401) await clearTeacher();   // expired: ask for the code again
          return setRoute({ name: 'teacher-login' });
        }
      }
      setRoute({ name: 'welcome' });
    })();
  }, []);
  const go = useCallback((r: Route) => setRoute(r), []);

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: t.bg }}>
      <StatusBar barStyle={dark ? 'light-content' : 'dark-content'} backgroundColor={t.bg} />
      {!route ? <ActivityIndicator style={{ flex: 1 }} color={t.primary} />
        : route.name === 'welcome' ? <Welcome go={go} />
        : route.name === 'student-setup' ? <StudentSetup go={go} />
        : route.name === 'student' ? <StudentHome profile={route.profile} fresh={route.fresh} go={go} />
        : route.name === 'teacher-login' ? <TeacherLogin go={go} />
        : route.name === 'teacher-subjects' ? <TeacherSubjects r={route} go={go} />
        : route.name === 'teacher-room' ? <TeacherRoom r={route} go={go} />
        : route.name === 'teacher-sheet' ? <SheetScreen r={route} go={go} />
        : <><Lab /><View style={{ padding: 16 }}><Button kind="ghost" title="Back" onPress={() => go({ name: 'welcome' })} /></View></>}
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

function Welcome({ go }: { go: (r: Route) => void }) {
  const t = useTheme();
  return (
    <ScrollView contentContainerStyle={s.page}>
      <View style={{ alignItems: 'center', gap: 10, marginTop: 40 }}>
        <Mark />
        <Text style={[s.title, { color: t.text }]}>NetPresence</Text>
        <Text style={[s.lead, { color: t.sub }]}>Attendance, the moment class starts.</Text>
      </View>
      <View style={{ gap: 12, marginTop: 24 }}>
        <Button title="I'm a student" onPress={() => go({ name: 'student-setup' })} />
        <Button kind="ghost" title="I'm a teacher" onPress={() => go({ name: 'teacher-login' })} />
      </View>
      <Pressable onPress={() => go({ name: 'lab' })} hitSlop={12}><Text style={[s.fine, { color: t.sub }]}>Signal lab</Text></Pressable>
    </ScrollView>
  );
}

// ---------------------------------------------------------------------------------------------------------- teacher
function TeacherLogin({ go }: { go: (r: Route) => void }) {
  const t = useTheme();
  const [code, setCode] = useState('');
  const [server, setServer] = useState('http://192.168.');
  const [showServer, setShowServer] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  useEffect(() => { loadServer().then(setServer); }, []);

  const login = async () => {
    setBusy(true); setErr('');
    const base = normalizeUrl(server);
    try {
      const r = await new NetPresenceApi(base).teacherLogin(code.trim());
      await saveServer(base);
      await saveTeacher({ baseUrl: base, token: r.token, name: r.teacher.name });
      go({ name: 'teacher-subjects', base, token: r.token, teacher: r.teacher.name, subjects: r.subjects });
    } catch (e) {
      setErr(e instanceof ApiError && e.status === 429 ? 'Too many tries. Wait a minute and try again.' : explain(e, base));
      if (e instanceof ApiError && e.status === 0) setShowServer(true);
    } finally { setBusy(false); }
  };

  return (
    <ScrollView contentContainerStyle={s.page} keyboardShouldPersistTaps="handled">
      <Text style={[s.title, { color: t.text, marginTop: 24 }]}>Teacher</Text>
      <Card style={{ gap: 16 }}>
        <Field label="YOUR CODE" placeholder="Enter your code" autoCapitalize="characters" secureTextEntry value={code} onChangeText={setCode} onSubmitEditing={login} />
        {showServer && <Field label="SERVER ADDRESS" autoCapitalize="none" keyboardType="url" value={server} onChangeText={setServer} />}
        {err ? <Banner kind="err" text={err} /> : null}
        <Button title={busy ? 'Checking…' : 'Continue'} onPress={login} disabled={busy || code.trim().length < 4} />
      </Card>
      {!showServer && <Pressable onPress={() => setShowServer(true)} hitSlop={12}><Text style={[s.fine, { color: t.sub }]}>Change server address</Text></Pressable>}
      <Button kind="ghost" title="Back" onPress={() => go({ name: 'welcome' })} />
    </ScrollView>
  );
}

function TeacherSubjects({ r, go }: { r: Extract<Route, { name: 'teacher-subjects' }>; go: (x: Route) => void }) {
  const t = useTheme();
  return (
    <ScrollView contentContainerStyle={s.page}>
      <View style={s.head}>
        <View><Text style={[s.hello, { color: t.sub }]}>Welcome,</Text><Text style={[s.name, { color: t.text }]}>{r.teacher}</Text></View>
        <Pressable onPress={async () => { await clearTeacher(); go({ name: 'welcome' }); }} hitSlop={12}><Text style={{ color: t.sub, fontSize: 14 }}>Log out</Text></Pressable>
      </View>
      <Text style={[s.status, { color: t.text, textAlign: 'left' }]}>Choose a subject</Text>
      {r.subjects.length === 0 && <Banner kind="warn" text="No subjects are assigned to you yet." />}
      {r.subjects.map((sub) => (
        <Pressable key={sub.subject_id} accessibilityRole="button" onPress={() => go({ name: 'teacher-room', base: r.base, token: r.token, subject: sub })}
          style={({ pressed }) => [s.subject, { backgroundColor: t.surface, borderColor: t.border, opacity: pressed ? 0.85 : 1 }]}>
          <View style={{ flex: 1 }}>
            <Text style={[s.subjectName, { color: t.text }]}>{sub.name}</Text>
            <Text style={{ color: t.sub, fontSize: 14 }}>{sub.code} · {sub.roster_size} students{sub.last_pct != null ? ` · last class ${Math.round(sub.last_pct)}%` : ''}</Text>
          </View>
          <Pressable accessibilityRole="button" onPress={() => go({ name: 'teacher-sheet', from: r, subject: sub })} hitSlop={8}
            style={[s.mini, { backgroundColor: t.input, borderWidth: 1, borderColor: t.border }]}><Text style={{ color: t.text, fontWeight: '700' }}>Register</Text></Pressable>
          <Text style={{ color: t.primary, fontSize: 22, fontWeight: '700' }}>›</Text>
        </Pressable>
      ))}
    </ScrollView>
  );
}


// ---------------------------------------------------------------------------------------------------------- the register
const MARK = { P: 'ok', A: 'err', F: 'warn', '-': 'sub' } as const;
const dayLabel = (at: number | null) => { if (!at) return ['?', '']; const d = new Date(at * 1000); const p2 = (n: number) => String(n).padStart(2, '0'); return [`${d.getDate()}/${d.getMonth() + 1}`, `${p2(d.getHours())}:${p2(d.getMinutes())}`]; };
const localStamp = (at: number | null) => { const [a, b] = dayLabel(at); return at ? `${a} ${b}` : ''; };

function SheetScreen({ r, go }: { r: Extract<Route, { name: 'teacher-sheet' }>; go: (x: Route) => void }) {
  const t = useTheme();
  const [sheet, setSheet] = useState<AttendanceSheet | null>(null);
  const [err, setErr] = useState('');
  const load = useCallback(() => {
    setErr('');
    new NetPresenceApi(r.from.base).teacherSheet(r.from.token, r.subject.subject_id).then(setSheet)
      .catch((e) => setErr(explain(e, r.from.base)));
  }, [r]);
  useEffect(load, [load]);
  const W = { roll: 92, name: 140, mark: 40, pct: 52 };
  const cell = (txt: string, w: number, color?: string, bold = false, align: 'left' | 'center' = 'center') =>
    <Text numberOfLines={1} style={{ width: w, color: color ?? t.text, fontSize: 13, fontWeight: bold ? '700' : '400', textAlign: align, paddingVertical: 8 }}>{txt}</Text>;
  const held = sheet?.sessions.length ?? 0;
  const resetPhone = (id: string, name: string) => Alert.alert(`Reset ${name}'s phone?`,
    `${id} will be able to register a new phone (lost phone, reinstalled app). Their old registration is removed.`, [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Reset', style: 'destructive', onPress: () => new NetPresenceApi(r.from.base).resetStudentPhone(r.from.token, id)
        .then(() => Alert.alert('Done', `${id} can register again.`)).catch((e) => Alert.alert('Could not reset', explain(e, r.from.base))) },
    ]);
  return (
    <View style={{ flex: 1 }}>
      <View style={{ padding: 20, paddingBottom: 8, gap: 4 }}>
        <Text style={[s.hello, { color: t.sub }]}>{r.subject.code} · register</Text>
        <Text style={[s.name, { color: t.text }]} numberOfLines={1}>{r.subject.name}</Text>
        {sheet && <Text style={{ color: t.sub, fontSize: 13 }}>{held} class{held === 1 ? '' : 'es'} held · {sheet.students.length} students · long-press a student to reset their phone</Text>}
      </View>
      {err ? <View style={{ paddingHorizontal: 20 }}><Banner kind="err" text={err} /></View> : null}
      {!sheet && !err && <ActivityIndicator style={{ marginTop: 40 }} color={t.primary} />}
      {sheet && held === 0 && <View style={{ paddingHorizontal: 20 }}><Banner kind="warn" text="No finished roll calls yet. Start a class and tap Finish to fill the register." /></View>}
      {sheet && held > 0 && (
        <ScrollView>
          <ScrollView horizontal showsHorizontalScrollIndicator>
            <View>
              <View style={{ flexDirection: 'row', borderBottomWidth: 1, borderColor: t.border, backgroundColor: t.surface }}>
                {cell('Roll no', W.roll, t.sub, true, 'left')}{cell('Name', W.name, t.sub, true, 'left')}
                {sheet.sessions.map((x) => { const [a, b] = dayLabel(x.at); return (
                  <View key={x.session_id} style={{ width: W.mark, alignItems: 'center', paddingVertical: 4 }}>
                    <Text style={{ color: t.sub, fontSize: 11, fontWeight: '700' }}>{a}</Text><Text style={{ color: t.sub, fontSize: 9 }}>{b}</Text>
                  </View>); })}
                {cell('%', W.pct, t.sub, true)}
              </View>
              <View style={{ flexDirection: 'row', backgroundColor: t.input }}>
                {cell('', W.roll)}{cell('Present', W.name, t.sub, false, 'left')}
                {sheet.sessions.map((x) => <View key={x.session_id}>{cell(String(x.present), W.mark, t.ok, true)}</View>)}
                {cell('', W.pct)}
              </View>
              {sheet.students.map((st) => (
                <Pressable key={st.student_id} onLongPress={() => resetPhone(st.student_id, st.name)} delayLongPress={500}
                  style={{ flexDirection: 'row', borderTopWidth: StyleSheet.hairlineWidth, borderColor: t.border }}>
                  {cell(st.student_id, W.roll, t.text, false, 'left')}{cell(st.name, W.name, t.text, false, 'left')}
                  {st.marks.map((m, i) => <View key={i}>{cell(m, W.mark, t[MARK[m as keyof typeof MARK] ?? 'sub'], m !== '-')}</View>)}
                  {cell(st.pct == null ? '-' : `${st.pct}`, W.pct, st.pct != null && st.pct < 75 ? t.err : t.text, true)}
                </Pressable>
              ))}
            </View>
          </ScrollView>
        </ScrollView>
      )}
      <View style={{ padding: 16, gap: 10 }}>
        {sheet && held > 0 && <Button title="Share register (CSV)" onPress={() => Share.share({ message: sheetCsv(sheet, localStamp) })} />}
        <View style={{ flexDirection: 'row', gap: 10 }}>
          <View style={{ flex: 1 }}><Button kind="ghost" title="Refresh" onPress={load} /></View>
          <View style={{ flex: 1 }}><Button kind="ghost" title="Back" onPress={() => go(r.from)} /></View>
        </View>
      </View>
    </View>
  );
}

const STATUS_ORDER = ['FLAGGED', 'PENDING', 'NOT_JOINED', 'PRESENT', 'ABSENT'];
const statusLabel: Record<string, string> = { PRESENT: 'Present', PENDING: 'Checking', FLAGGED: 'Check this', NOT_JOINED: 'Not joined', ABSENT: 'Absent' };

function TeacherRoom({ r, go }: { r: Extract<Route, { name: 'teacher-room' }>; go: (x: Route) => void }) {
  const t = useTheme();
  const radio = useRef(new NativeRadio()).current;
  const roll = useRef<TeacherRoll | null>(null);
  const [live, setLive] = useState<TeacherLive | null>(null);
  const [err, setErr] = useState('');
  const [offline, setOffline] = useState(false);
  const [busy, setBusy] = useState(true);
  const [finished, setFinished] = useState(false);
  const [diag, setDiag] = useState<LiveDiag>({ radio: 'off', adverts: 0, foreign: 0, peers: [], sent: 0, failed: 0, log: [] });
  const board = useRef(new DiagBoard(setDiag)).current;

  useEffect(() => {
    let dead = false;
    setKeepAwake(true);
    deviceModel().catch(() => 'unknown').then((model) => {
      const tr = new TeacherRoll({
        api: new NetPresenceApi(r.base), keys: nativeKeys, radio, token: r.token, model, diag: board,
        onLive: (l) => { setLive(l); setOffline(false); },
        onError: (m, off) => { setOffline(off); if (!off) setErr(m); },
      });
      roll.current = tr;
      return tr.begin(r.subject.subject_id);
    }).then(() => { if (!dead) setBusy(false); })
      .catch((e) => { if (!dead) { setBusy(false); setErr(radio.lastError ? 'Bluetooth problem: ' + radio.lastError : explain(e, r.base)); } });
    return () => { dead = true; setKeepAwake(false); };
  }, []);

  const finish = async () => {
    try {
      const out = await roll.current!.finish();
      buzz(60);
      setFinished(true);
      setLive((l) => (l ? { ...l, rows: (out as { rows?: TeacherLive['rows'] }).rows ?? l.rows, status: 'closed' } : l));
    } catch (e) { setErr(explain(e, r.base)); }
  };
  const share = () => live && Share.share({ message: attendanceCsv(r.subject.code, live.rows.map((x) => ({ student_id: x.student_id, name: x.name, status: x.status === 'PRESENT' ? 'Present' : 'Absent' }))) });

  const c = live?.counts ?? {};
  const rows = [...(live?.rows ?? [])].sort((a, b) => STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status) || a.name.localeCompare(b.name));
  return (
    <ScrollView contentContainerStyle={s.page}>
      <Text style={[s.hello, { color: t.sub }]}>{r.subject.code}</Text>
      <Text style={[s.name, { color: t.text }]}>{r.subject.name}</Text>
      {busy && <View style={{ flexDirection: 'row', gap: 10, alignItems: 'center' }}><ActivityIndicator color={t.primary} /><Text style={{ color: t.sub }}>Starting…</Text></View>}
      <LivePanel d={diag} />
      {offline && <Banner kind="warn" text="Cannot reach the server - trying again." />}
      {err ? <Banner kind="err" text={err} /> : null}
      <Card style={{ alignItems: 'center', gap: 4 }}>
        <Text style={{ color: t.ok, fontSize: 56, fontWeight: '800' }}>{c.PRESENT ?? 0}<Text style={{ color: t.sub, fontSize: 24 }}> / {live?.roster_size ?? r.subject.roster_size}</Text></Text>
        <Text style={{ color: t.sub, fontSize: 15 }}>{finished ? 'Final attendance' : 'present - keep this phone on and near the front'}</Text>
      </Card>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
        {STATUS_ORDER.map((k) => <Chip key={k} text={`${statusLabel[k]} ${c[k] ?? 0}`} tone={k === 'PRESENT' && (c[k] ?? 0) > 0 ? 'ok' : 'neutral'} />)}
      </View>
      {!finished && <Button title={(live?.elapsed_s ?? 0) < LIVE_BEST_AFTER_S ? `Finish (most accurate in ${Math.ceil(LIVE_BEST_AFTER_S - (live?.elapsed_s ?? 0))} s)` : 'Finish roll call'} onPress={finish} disabled={busy || !live} />}
      {finished && <Button title="Share list (CSV)" onPress={share} />}
      {finished && <Button kind="ghost" title="Back to subjects" onPress={async () => {
        try {
          const subjects = await new NetPresenceApi(r.base).teacherSubjects(r.token);
          const ts = await loadTeacher();
          go({ name: 'teacher-subjects', base: r.base, token: r.token, teacher: ts?.name ?? 'Teacher', subjects });
        } catch { go({ name: 'teacher-login' }); }
      }} />}
      {rows.filter((x) => x.status !== 'NOT_JOINED' || finished || (live?.elapsed_s ?? 0) > 20).map((x) => (
        <View key={x.student_id} style={[s.row, { borderColor: t.border, backgroundColor: t.surface }]}>
          <View style={{ flex: 1 }}>
            <Text style={{ color: t.text, fontSize: 16, fontWeight: '600' }} numberOfLines={1}>{x.name}</Text>
            <Text style={{ color: t.sub, fontSize: 12 }}>{x.student_id}{x.reason ? ` · ${x.reason}` : ''}</Text>
          </View>
          {x.status === 'FLAGGED' && !finished ? (
            <View style={{ flexDirection: 'row', gap: 6 }}>
              <Pressable onPress={() => roll.current?.adjudicate(x.student_id, 'PRESENT')} style={[s.mini, { backgroundColor: t.okBg }]}><Text style={{ color: t.ok, fontWeight: '700' }}>Present</Text></Pressable>
              <Pressable onPress={() => roll.current?.adjudicate(x.student_id, 'ABSENT')} style={[s.mini, { backgroundColor: t.errBg }]}><Text style={{ color: t.err, fontWeight: '700' }}>Absent</Text></Pressable>
            </View>
          ) : <Text style={{ color: tone(t, x.status), fontWeight: '700' }}>{statusLabel[x.status]}</Text>}
        </View>
      ))}
    </ScrollView>
  );
}
const tone = (t: Theme, st: string) => (st === 'PRESENT' ? t.ok : st === 'FLAGGED' ? t.warn : st === 'ABSENT' ? t.err : t.sub);

// ---------------------------------------------------------------------------------------------------------- student
function StudentSetup({ go }: { go: (r: Route) => void }) {
  const t = useTheme();
  const [form, setForm] = useState({ studentId: '', name: '', code: '' });
  const [server, setServer] = useState('http://192.168.');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  useEffect(() => { loadServer().then(setServer); }, []);
  const ready = form.studentId.trim() && form.name.trim() && server.trim().length > 8;

  const register = async () => {
    setBusy(true); setErr('');
    const base = normalizeUrl(server);
    const api = new NetPresenceApi(base);
    try { await api.health(); } catch (e) { setBusy(false); setErr(explain(e, base)); return; }
    // The fingerprint says "I am the person holding this phone, and I will use only this phone".
    const bio = await confirmBiometric('Register this phone as yours for attendance');
    if (bio === 'cancel') { setBusy(false); setErr('Registration needs your fingerprint (or face) to confirm this is your phone.'); return; }
    if (bio === 'unavailable') { setBusy(false); setErr('Set up a fingerprint, face or screen lock in your phone settings first. Attendance asks for it every class.'); return; }
    try {
      await enroll(api, nativeKeys, {
        studentId: form.studentId.trim().toUpperCase(), name: form.name.trim(), model: await deviceModel(),
        enrolCode: form.code.trim() || undefined, installId: await installId(), platform: Platform.OS, biometric: true,
      });
      const p = { baseUrl: base, studentId: form.studentId.trim().toUpperCase(), name: form.name.trim() };
      await saveProfile(p); await saveServer(base);
      buzz(60);
      go({ name: 'student', profile: p, fresh: true });
    } catch (e) {
      setErr(e instanceof ApiError && e.status === 403 ? 'That class code is wrong or missing.'
        : e instanceof ApiError && e.status === 409 ? e.message : explain(e, base));
    } finally { setBusy(false); }
  };

  return (
    <ScrollView contentContainerStyle={s.page} keyboardShouldPersistTaps="handled">
      <Text style={[s.title, { color: t.text, marginTop: 24 }]}>Register this phone</Text>
      <Text style={[s.lead, { color: t.sub, textAlign: 'left' }]}>Once. After this, attendance happens by itself.</Text>
      <Card style={{ gap: 16 }}>
        <Field label="ROLL NUMBER" placeholder="e.g. 21CS042" autoCapitalize="characters" value={form.studentId} onChangeText={(studentId) => setForm({ ...form, studentId })} />
        <Field label="FULL NAME" placeholder="As on the register" value={form.name} onChangeText={(name) => setForm({ ...form, name })} />
        <Field label="CLASS CODE" placeholder="From your teacher" autoCapitalize="characters" value={form.code} onChangeText={(code) => setForm({ ...form, code })} />
        <Field label="SERVER ADDRESS" autoCapitalize="none" keyboardType="url" value={server} onChangeText={setServer} />
        {err ? <Banner kind="err" text={err} /> : null}
        <Button title={busy ? 'Registering…' : 'Verify with fingerprint'} onPress={register} disabled={busy || !ready} />
      </Card>
      <Text style={[s.fine, { color: t.sub }]}>This phone is locked to you. If you change phones, your teacher resets it.</Text>
      <Button kind="ghost" title="Back" onPress={() => go({ name: 'welcome' })} />
    </ScrollView>
  );
}

function StudentHome({ profile, fresh, go }: { profile: Profile; fresh: boolean; go: (r: Route) => void }) {
  const t = useTheme();
  const radio = useRef(new NativeRadio()).current;
  const [st, setSt] = useState<StudentState>({ phase: 'signing_in', nearby: 0 });
  const [verified, setVerified] = useState(fresh);
  const [menu, setMenu] = useState(false);
  const buzzed = useRef<string>('');
  const [diag, setDiag] = useState<LiveDiag>({ radio: 'off', adverts: 0, foreign: 0, peers: [], sent: 0, failed: 0, log: [] });
  const board = useRef(new DiagBoard(setDiag)).current;

  useEffect(() => {
    if (fresh) { const id = setTimeout(() => setVerified(false), 1800); return () => clearTimeout(id); }
  }, [fresh]);

  const runnerRef = useRef<StudentRunner | null>(null);
  useEffect(() => {
    const runner = new StudentRunner({ api: new NetPresenceApi(profile.baseUrl), keys: nativeKeys, radio, studentId: profile.studentId, onState: setSt, diag: board, confirm: confirmBiometric });
    runnerRef.current = runner;
    setKeepAwake(true);
    void runner.run();
    return () => { runner.stop(); setKeepAwake(false); };
  }, [profile.baseUrl, profile.studentId]);

  useEffect(() => {
    const k = `${st.sessionId}:${st.status}`;
    if (st.status === 'PRESENT' && buzzed.current !== k) { buzzed.current = k; buzz(Platform.OS === 'android' ? [0, 50, 50, 50] : 50); }
  }, [st.status, st.sessionId]);

  const view = describe(st, t, radio.lastError);
  const reset = async () => { await clearProfile(); go({ name: 'welcome' }); };

  if (verified) {
    return (
      <View style={s.center}>
        <View style={[s.orb, { backgroundColor: t.okBg, borderColor: t.ok }]}><Text style={{ color: t.ok, fontSize: 64 }}>✓</Text></View>
        <Text style={[s.title, { color: t.text }]}>Phone verified</Text>
        <Text style={[s.lead, { color: t.sub }]}>{profile.name}, this phone is yours now.{'\n'}Getting ready…</Text>
      </View>
    );
  }
  return (
    <ScrollView contentContainerStyle={[s.page, { flexGrow: 1 }]}>
      <View style={s.head}>
        <View><Text style={[s.hello, { color: t.sub }]}>{profile.studentId}</Text><Text style={[s.name, { color: t.text }]} numberOfLines={1}>{profile.name}</Text></View>
        <Pressable accessibilityLabel="Menu" onPress={() => setMenu(!menu)} hitSlop={12}><Text style={{ color: t.sub, fontSize: 28 }}>⋯</Text></Pressable>
      </View>
      {menu && (
        <Card style={{ gap: 10 }}>
          <Button kind="ghost" title="Signal lab" onPress={() => go({ name: 'lab' })} />
          <Button kind="ghost" title="Remove this phone's registration" onPress={reset} />
        </Card>
      )}
      <View style={s.center}>
        <View style={[s.orb, { backgroundColor: view.bg, borderColor: view.fg }]}>
          {view.spin ? <ActivityIndicator size="large" color={view.fg} /> : <Text style={{ color: view.fg, fontSize: 64 }}>{view.icon}</Text>}
        </View>
        <Text style={[s.title, { color: t.text, textAlign: 'center' }]}>{view.title}</Text>
        <Text style={[s.lead, { color: t.sub }]}>{view.sub}</Text>
        {st.phase === 'live' && <Chip text={`${st.nearby} phone${st.nearby === 1 ? '' : 's'} nearby`} tone={st.nearby > 0 ? 'ok' : 'neutral'} />}
        {st.subject && st.phase !== 'idle' && <Chip text={`${st.subject.code} · ${st.subject.name}`} />}
      </View>
      {view.banner ? <Banner kind={view.banner.kind} text={view.banner.text} /> : null}
      {st.phase === 'need_biometric' && <Button title="Use fingerprint" onPress={() => runnerRef.current?.retryConfirm()} />}
      {st.phase === 'not_registered' && <Button title="Register this phone again" onPress={async () => { await clearProfile(); go({ name: 'student-setup' }); }} />}
      <LivePanel d={diag} />
    </ScrollView>
  );
}

function describe(st: StudentState, t: Theme, radioErr: string | null) {
  const base = { bg: t.surface, fg: t.primary, icon: '', spin: false, title: '', sub: '', banner: undefined as undefined | { kind: 'err' | 'warn' | 'ok'; text: string } };
  switch (st.phase) {
    case 'signing_in': return { ...base, spin: true, title: 'Signing in', sub: 'Just a moment' };
    case 'idle': return { ...base, icon: '·', title: 'You\'re all set', sub: 'Nothing to do. Your attendance is taken automatically when your teacher starts the class. Keep Bluetooth on.' };
    case 'confirming': return { ...base, icon: '☝', title: 'Confirm it is you', sub: st.subject ? `Use your fingerprint, face or screen lock to join ${st.subject.name}.` : 'Use your fingerprint, face or screen lock to join this class.' };
    case 'need_biometric': return { ...base, bg: t.warnBg, fg: t.warn, icon: '☝', title: 'Confirm to join', sub: st.message ?? 'Use your fingerprint, face or screen lock.' };
    case 'joining': return { ...base, spin: true, title: 'Joining…', sub: st.subject ? st.subject.name : 'Class is starting' };
    case 'live':
      if (st.status === 'PRESENT') return { ...base, bg: t.okBg, fg: t.ok, icon: '✓', title: 'Present', sub: `${st.timeToPresentMs != null ? `Confirmed in ${(st.timeToPresentMs / 1000).toFixed(1)} s. ` : ''}You are done. Keep the app open: your phone now just helps confirm the students around you.` };
      if (st.status === 'FLAGGED') return { ...base, bg: t.warnBg, fg: t.warn, icon: '!', title: 'Your teacher will confirm', sub: 'Stay where you are.' };
      return { ...base, spin: true, title: 'Reaching nearby phones…', sub: 'Keep the app open.', banner: radioErr ? { kind: 'err' as const, text: radioErr === 'NP-ERR-BT-OFF' ? 'Bluetooth is off. Turn it on.' : `Bluetooth problem (${radioErr}).` } : undefined };
    case 'closed': return { ...base, bg: st.result === 'PRESENT' ? t.okBg : t.surface, fg: st.result === 'PRESENT' ? t.ok : t.sub, icon: st.result === 'PRESENT' ? '✓' : '·', title: st.result === 'PRESENT' ? 'You were marked present' : 'Roll call finished', sub: st.result === 'PRESENT' ? '' : 'See your teacher if this looks wrong.' };
    case 'not_registered': return { ...base, bg: t.warnBg, fg: t.warn, icon: '?', title: 'Phone not recognised', sub: st.message ?? 'Register this phone again.' };
    case 'not_in_class': return { ...base, bg: t.errBg, fg: t.err, icon: '✕', title: 'Not in this class', sub: st.message ?? 'You are not on the list for this subject.' };
    case 'offline': return { ...base, bg: t.warnBg, fg: t.warn, icon: '⚠', title: 'No connection', sub: st.message ?? 'Trying again.' };
    default: return { ...base, bg: t.errBg, fg: t.err, icon: '!', title: 'Something went wrong', sub: st.message ?? 'Trying again.' };
  }
}

const s = StyleSheet.create({
  page: { padding: 20, gap: 16, paddingBottom: 40 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 16, padding: 24, minHeight: 420 },
  orb: { width: 168, height: 168, borderRadius: 84, borderWidth: 4, alignItems: 'center', justifyContent: 'center' },
  title: { fontSize: 30, fontWeight: '800', letterSpacing: -0.5 },
  lead: { fontSize: 15, textAlign: 'center', lineHeight: 22 },
  fine: { fontSize: 13, textAlign: 'center', lineHeight: 18, paddingHorizontal: 12, paddingVertical: 8 },
  head: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginTop: 8 },
  hello: { fontSize: 14 }, name: { fontSize: 26, fontWeight: '800', maxWidth: 280 },
  status: { fontSize: 18, fontWeight: '700' },
  mark: { width: 76, height: 76, borderRadius: 22, alignItems: 'center', justifyContent: 'center' },
  dot: { width: 10, height: 10, borderRadius: 5, position: 'absolute' },
  arc: { position: 'absolute', borderWidth: 3, borderLeftColor: 'transparent', borderBottomColor: 'transparent', transform: [{ rotate: '-45deg' }] },
  subject: { flexDirection: 'row', alignItems: 'center', borderWidth: 1, borderRadius: 18, padding: 18, gap: 12 },
  subjectName: { fontSize: 18, fontWeight: '700', marginBottom: 2 },
  row: { flexDirection: 'row', alignItems: 'center', borderWidth: 1, borderRadius: 14, padding: 12, gap: 10 },
  mini: { borderRadius: 10, paddingHorizontal: 12, paddingVertical: 8 },
});
