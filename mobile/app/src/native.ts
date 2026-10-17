import { NativeEventEmitter, NativeModules, PermissionsAndroid, Platform } from 'react-native';
import type { KeyStore, Radio, RadioSample } from '../../core/src';

const N = NativeModules.NetPresenceNative as {
  publicKey(): Promise<string>;
  sign(message: string): Promise<string>;
  deviceModel(): Promise<string>;
  startRadio(name: string, serviceUuid: string): Promise<void>;
  stopRadio(): Promise<void>;
  setKeepAwake?(on: boolean): void;
};

/** Stops the screen locking mid roll-call (a locked iPhone stops scanning). No-op if the native side lacks it. */
export const setKeepAwake = (on: boolean) => { try { N.setKeepAwake?.(on); } catch { /* cosmetic */ } };

export const deviceModel = (): Promise<string> => N.deviceModel();

/** Hardware-backed key: Secure Enclave (iOS) / Android Keystore. The private key never leaves the chip. */
export const nativeKeys: KeyStore = {
  publicKeyB64: () => N.publicKey(),
  signB64: (m) => N.sign(m),
};

export async function ensureBlePermissions(): Promise<void> {
  if (Platform.OS !== 'android') return; // iOS prompts itself on first CoreBluetooth use
  const api = Number(Platform.Version);
  const wanted =
    api >= 31
      ? [PermissionsAndroid.PERMISSIONS.BLUETOOTH_SCAN, PermissionsAndroid.PERMISSIONS.BLUETOOTH_ADVERTISE, PermissionsAndroid.PERMISSIONS.BLUETOOTH_CONNECT]
      : [PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION];
  const res = await PermissionsAndroid.requestMultiple(wanted);
  if (!wanted.every((p) => res[p] === PermissionsAndroid.RESULTS.GRANTED)) {
    throw new Error('Bluetooth permission is required to mark attendance.');
  }
}

/** Errors from the native side arrive as pseudo-samples named "NP-ERR-..."; surface them instead of hearing nothing. */
export class NativeRadio implements Radio {
  private sub?: { remove(): void };
  lastError: string | null = null;

  async start(name: string, uuid: string, onSample: (s: RadioSample) => void) {
    await ensureBlePermissions();
    this.lastError = null;
    this.sub = new NativeEventEmitter(NativeModules.NetPresenceNative).addListener('NPSample', (s: RadioSample) => {
      if (s.name.startsWith('NP-ERR-')) this.lastError = s.name;
      else onSample(s);
    });
    await N.startRadio(name, uuid);
  }

  async stop() {
    this.sub?.remove();
    this.sub = undefined;
    await N.stopRadio();
  }
}
