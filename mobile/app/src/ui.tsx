import React from 'react';
import { Pressable, StyleSheet, Text, TextInput, TextInputProps, View, ViewStyle } from 'react-native';
import { useTheme } from './theme';

export function Card({ children, style }: { children: React.ReactNode; style?: ViewStyle }) {
  const t = useTheme();
  return <View style={[s.card, { backgroundColor: t.surface, borderColor: t.border }, style]}>{children}</View>;
}

export function Field({ label, hint, ...p }: { label: string; hint?: string } & TextInputProps) {
  const t = useTheme();
  return (
    <View style={{ gap: 6 }}>
      <Text style={[s.label, { color: t.sub }]}>{label}</Text>
      <TextInput placeholderTextColor={t.sub} autoCorrect={false} {...p}
        style={[s.input, { backgroundColor: t.input, borderColor: t.border, color: t.text }]} />
      {hint ? <Text style={[s.hint, { color: t.sub }]}>{hint}</Text> : null}
    </View>
  );
}

export function Button({ title, onPress, disabled, kind = 'primary' }: { title: string; onPress: () => void; disabled?: boolean; kind?: 'primary' | 'ghost' }) {
  const t = useTheme();
  const ghost = kind === 'ghost';
  return (
    <Pressable accessibilityRole="button" onPress={onPress} disabled={disabled}
      style={({ pressed }) => [s.btn, { backgroundColor: ghost ? 'transparent' : t.primary, borderColor: ghost ? t.border : t.primary, opacity: disabled ? 0.45 : pressed ? 0.85 : 1 }]}>
      <Text style={[s.btnT, { color: ghost ? t.text : t.primaryText }]}>{title}</Text>
    </Pressable>
  );
}

export function Banner({ kind, text }: { kind: 'err' | 'warn' | 'ok'; text: string }) {
  const t = useTheme();
  const [bg, fg] = kind === 'err' ? [t.errBg, t.err] : kind === 'warn' ? [t.warnBg, t.warn] : [t.okBg, t.ok];
  return <View style={[s.banner, { backgroundColor: bg }]}><Text style={{ color: fg, fontSize: 14, lineHeight: 20 }}>{text}</Text></View>;
}

export function Chip({ text, tone = 'neutral' }: { text: string; tone?: 'neutral' | 'ok' }) {
  const t = useTheme();
  return (
    <View style={[s.chip, { backgroundColor: tone === 'ok' ? t.okBg : t.surface, borderColor: t.border }]}>
      <Text style={{ color: tone === 'ok' ? t.ok : t.sub, fontSize: 13, fontWeight: '600' }}>{text}</Text>
    </View>
  );
}

const s = StyleSheet.create({
  card: { borderRadius: 20, borderWidth: 1, padding: 18 },
  label: { fontSize: 13, fontWeight: '600', letterSpacing: 0.3 },
  hint: { fontSize: 12, lineHeight: 17 },
  input: { borderWidth: 1, borderRadius: 14, paddingHorizontal: 14, paddingVertical: 13, fontSize: 16 },
  btn: { borderWidth: 1, borderRadius: 14, paddingVertical: 15, alignItems: 'center' },
  btnT: { fontSize: 16, fontWeight: '700' },
  banner: { borderRadius: 14, padding: 14 },
  chip: { borderWidth: 1, borderRadius: 999, paddingHorizontal: 12, paddingVertical: 6 },
});
