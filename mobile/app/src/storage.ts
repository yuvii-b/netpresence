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
