import AsyncStorage from '@react-native-async-storage/async-storage';

export interface Profile { baseUrl: string; studentId: string; name: string }
const KEY = 'np.profile.v2';
const URL_KEY = 'np.server.v1';

export async function loadProfile(): Promise<Profile | null> {
  try { const s = await AsyncStorage.getItem(KEY); return s ? (JSON.parse(s) as Profile) : null; } catch { return null; }
}
export const saveProfile = (p: Profile) => AsyncStorage.setItem(KEY, JSON.stringify(p));
export const clearProfile = () => AsyncStorage.removeItem(KEY);

/** The server address is remembered for both roles (the teacher has no profile). */
export async function loadServer(): Promise<string> {
  try { return (await AsyncStorage.getItem(URL_KEY)) ?? 'http://192.168.'; } catch { return 'http://192.168.'; }
}
export const saveServer = (u: string) => AsyncStorage.setItem(URL_KEY, u).catch(() => undefined);

/** The teacher stays signed in: the server token is kept (12 h lifetime) so reopening the app goes straight to the subjects. */
export interface TeacherSession { baseUrl: string; token: string; name: string; at: number }
const T_KEY = 'np.teacher.v1';
export const TEACHER_SESSION_MS = 11 * 3600 * 1000;   // a little under the server's 12 h token life
export async function loadTeacher(): Promise<TeacherSession | null> {
  try {
    const s = await AsyncStorage.getItem(T_KEY);
    const t = s ? (JSON.parse(s) as TeacherSession) : null;
    return t && Date.now() - t.at < TEACHER_SESSION_MS ? t : null;
  } catch { return null; }
}
export const saveTeacher = (t: Omit<TeacherSession, 'at'>) => AsyncStorage.setItem(T_KEY, JSON.stringify({ ...t, at: Date.now() })).catch(() => undefined);
export const clearTeacher = () => AsyncStorage.removeItem(T_KEY).catch(() => undefined);
