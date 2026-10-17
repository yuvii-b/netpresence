import { useColorScheme } from 'react-native';

const light = {
  bg: '#F4F6FB', surface: '#FFFFFF', border: '#E3E7F0', text: '#0F172A', sub: '#5B6577',
  primary: '#4F46E5', primaryText: '#FFFFFF', ok: '#16A34A', okBg: '#E8F7EE', warn: '#B45309', warnBg: '#FEF3E2',
  err: '#DC2626', errBg: '#FDECEC', ring: '#C7D2FE', input: '#F8FAFD',
};
const dark: typeof light = {
  bg: '#0B1020', surface: '#141A2E', border: '#232B45', text: '#F1F5F9', sub: '#9AA6BD',
  primary: '#7C83FF', primaryText: '#0B1020', ok: '#34D399', okBg: '#10281F', warn: '#FBBF24', warnBg: '#2B2110',
  err: '#F87171', errBg: '#2E1517', ring: '#2B3466', input: '#0F1527',
};
export type Theme = typeof light;
export const useTheme = (): Theme => (useColorScheme() === 'dark' ? dark : light);
