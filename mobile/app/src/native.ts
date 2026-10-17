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

const RADIO_ERRORS: Record<string, string> = {
  'NP-ERR-BT-OFF': 'Bluetooth is off. Turn it on and try again.',
  'NP-ERR-BT-UNAUTHORIZED': 'Bluetooth is not allowed for NetPresence. Allow it in Settings.',
  'NP-ERR-BT-UNSUPPORTED': 'This phone does not support Bluetooth Low Energy.',
  'NP-ERR-ADV-UNSUPPORTED': 'This phone cannot broadcast over Bluetooth, so classmates cannot hear it. Ask your teacher to mark you.',
};
export const describeRadioError = (code: string) => RADIO_ERRORS[code] ?? `Bluetooth problem (${code}).`;

/**
 * The native side sends samples in batches ("NPSamples", every 200 ms) so ~900 adverts/s in a full room cost ~5 bridge
 * events/s. Native errors arrive as pseudo-samples named "NP-ERR-..."; they are kept in lastError, not counted.
 */
export class NativeRadio implements Radio {
  private sub?: { remove(): void };
  lastError: string | null = null;

  async start(name: string, uuid: string, onSample: (s: RadioSample) => void) {
    await ensureBlePermissions();
    this.lastError = null;
    this.sub?.remove();
    this.sub = new NativeEventEmitter(NativeModules.NetPresenceNative).addListener('NPSamples', (batch: RadioSample[]) => {
      for (const s of batch) {
        if (s.name.startsWith('NP-ERR-')) this.lastError = s.name;
        else onSample(s);
      }
    });
    try {
      await N.startRadio(name, uuid);
    } catch (e) {
      this.sub.remove();
      this.sub = undefined;
      throw e;
    }
  }

  async stop() {
    await N.stopRadio();                                   // native flushes its last batch first
    await new Promise<void>((r) => setTimeout(r, 50));     // let that final event arrive before unsubscribing
    this.sub?.remove();
    this.sub = undefined;
  }
}
