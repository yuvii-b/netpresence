import AsyncStorage from '@react-native-async-storage/async-storage';

export interface Profile { baseUrl: string; studentId: string; name: string }
const KEY = 'np.profile.v2';

export async function loadProfile(): Promise<Profile | null> {
  try { const s = await AsyncStorage.getItem(KEY); return s ? (JSON.parse(s) as Profile) : null; } catch { return null; }
}
export const saveProfile = (p: Profile) => AsyncStorage.setItem(KEY, JSON.stringify(p));
export const clearProfile = () => AsyncStorage.removeItem(KEY);
