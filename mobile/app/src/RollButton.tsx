import React, { useEffect, useRef } from 'react';
import { Animated, Easing, Pressable, StyleSheet, Text, View } from 'react-native';
import type { Phase } from './flow';
import { useTheme } from './theme';

const SIZE = 220;

/** The one big control. Pulsing rings while the phone is listening; a tick when done. */
export default function RollButton({ phase, secondsLeft, onPress }: { phase: Phase; secondsLeft: number; onPress: () => void }) {
  const t = useTheme();
  const pulse = useRef(new Animated.Value(0)).current;
  const busy = phase === 'joining' || phase === 'listening' || phase === 'sending';

  useEffect(() => {
    if (phase !== 'listening') { pulse.setValue(0); return; }
    const loop = Animated.loop(Animated.timing(pulse, { toValue: 1, duration: 1800, easing: Easing.out(Easing.quad), useNativeDriver: true }));
    loop.start();
    return () => loop.stop();
  }, [phase, pulse]);

  const ring = (delay: number) => {
    const p = Animated.modulo(Animated.add(pulse, delay), 1);
    return {
      opacity: p.interpolate({ inputRange: [0, 1], outputRange: [0.45, 0] }),
      transform: [{ scale: p.interpolate({ inputRange: [0, 1], outputRange: [1, 1.55] }) }],
    };
  };

  const done = phase === 'done';
  const bg = done ? t.ok : t.primary;
  const label =
    phase === 'joining' ? 'Joining…' : phase === 'listening' ? String(Math.max(0, secondsLeft)) :
    phase === 'sending' ? 'Sending…' : done ? '✓' : 'Mark me\npresent';
  const big = phase === 'listening' || done;

  return (
    <View style={s.wrap}>
      {phase === 'listening' && (<>
        <Animated.View pointerEvents="none" style={[s.ring, { borderColor: t.primary }, ring(0)]} />
        <Animated.View pointerEvents="none" style={[s.ring, { borderColor: t.primary }, ring(0.5)]} />
      </>)}
      <Pressable accessibilityRole="button" accessibilityLabel="Mark me present" disabled={busy} onPress={onPress}
        style={({ pressed }) => [s.btn, { backgroundColor: bg, opacity: pressed ? 0.9 : 1, shadowColor: bg }]}>
        <Text style={[s.txt, { color: t.primaryText, fontSize: big ? 64 : 26 }]}>{label}</Text>
        {phase === 'listening' && <Text style={[s.sub, { color: t.primaryText }]}>seconds left</Text>}
      </Pressable>
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { width: SIZE * 1.6, height: SIZE * 1.6, alignItems: 'center', justifyContent: 'center', alignSelf: 'center' },
  ring: { position: 'absolute', width: SIZE, height: SIZE, borderRadius: SIZE / 2, borderWidth: 3 },
  btn: { width: SIZE, height: SIZE, borderRadius: SIZE / 2, alignItems: 'center', justifyContent: 'center', elevation: 8, shadowOpacity: 0.35, shadowRadius: 18, shadowOffset: { width: 0, height: 8 } },
  txt: { fontWeight: '800', textAlign: 'center', lineHeight: undefined },
  sub: { fontSize: 14, fontWeight: '600', opacity: 0.85 },
});
